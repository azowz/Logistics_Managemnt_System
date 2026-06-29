"""Integration tests for authentication API routes.

Uses FastAPI TestClient with a SQLite in-memory database.  Redis is mocked via
unittest.mock.patch so no live Redis is needed.  All tables are created from
SQLAlchemy metadata before the first test runs and dropped after.
"""

from __future__ import annotations

import uuid
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.exceptions import install_exception_handlers
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_session
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import User

# ---------------------------------------------------------------------------
# Test application + session override
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+pysqlite:///:memory:"
_test_engine = create_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    # Single shared connection so the TestClient's request thread sees the same
    # in-memory DB that create_all/seed populated.
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_test_engine, autocommit=False, autoflush=False)

# Only the tables the auth flow touches. Full-metadata create_all is not
# SQLite-safe (the shipments table uses a PostgreSQL regex CHECK).
_AUTH_TABLES = [Tenant.__table__, User.__table__]


def _create_test_session() -> Generator[Session, None, None]:
    """FastAPI dependency override that uses the SQLite test session."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    """Create the auth tables once for the module; tear down after all tests."""
    Base.metadata.create_all(_test_engine, tables=_AUTH_TABLES)
    yield
    Base.metadata.drop_all(_test_engine, tables=_AUTH_TABLES)


@pytest.fixture(scope="module")
def test_app() -> FastAPI:
    from app.api.routes.auth import router as auth_router

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = _create_test_session
    return app


@pytest.fixture(scope="module")
def mock_redis_module() -> MagicMock:
    """Module-scoped mock Redis instance injected via patch."""
    r = MagicMock()
    r.getdel.return_value = None
    r.exists.return_value = 0
    r.setex.return_value = True
    r.delete.return_value = 1
    return r


@pytest.fixture(scope="module")
def client(test_app: FastAPI, mock_redis_module: MagicMock) -> TestClient:
    # Patch the source (covers lazy imports in AuthService.__init__) and the
    # bound reference in security.py (imported at module load time).
    with patch("app.core.redis.get_redis", return_value=mock_redis_module), \
         patch("app.core.security.get_redis", return_value=mock_redis_module):
        yield TestClient(test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers — seed tenant + user
# ---------------------------------------------------------------------------


def _seed_tenant_and_user(
    email: str = "seed@example.com",
    password: str = "password123",
    role: UserRole = UserRole.ADMIN,
) -> tuple[Tenant, User]:
    """Insert a tenant + user directly into the SQLite test DB."""
    session = _TestSession()
    try:
        tenant = Tenant(slug=f"slug-{uuid.uuid4().hex[:8]}", name="Test Org")
        session.add(tenant)
        session.flush()

        user = User(
            tenant_id=tenant.id,
            email=email,
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.refresh(tenant)
        return tenant, user
    finally:
        session.close()


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


def test_login_returns_200_on_valid_creds(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    _seed_tenant_and_user(email="login_ok@example.com", password="pass1234!")
    r = client.post("/auth/login", json={"email": "login_ok@example.com", "password": "pass1234!"})
    assert r.status_code == 200


def test_login_response_has_access_token(client: TestClient, mock_redis_module: MagicMock) -> None:
    _seed_tenant_and_user(email="login_tok@example.com", password="pass1234!")
    r = client.post("/auth/login", json={"email": "login_tok@example.com", "password": "pass1234!"})
    body = r.json()
    assert "access_token" in body
    assert body["access_token"]


def test_login_response_has_refresh_token(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    _seed_tenant_and_user(email="login_rt@example.com", password="pass1234!")
    r = client.post("/auth/login", json={"email": "login_rt@example.com", "password": "pass1234!"})
    body = r.json()
    assert "refresh_token" in body


def test_login_returns_401_on_wrong_password(client: TestClient) -> None:
    _seed_tenant_and_user(email="login_bad@example.com", password="correct1")
    r = client.post("/auth/login", json={"email": "login_bad@example.com", "password": "wrongone"})
    assert r.status_code == 401


def test_login_returns_401_on_unknown_email(client: TestClient) -> None:
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "pass1234!"})
    assert r.status_code == 401


def test_login_returns_422_on_short_password(client: TestClient) -> None:
    r = client.post("/auth/login", json={"email": "x@x.com", "password": "short"})
    assert r.status_code == 422


def test_login_with_valid_tenant_slug(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    session = _TestSession()
    tenant = Tenant(slug="acme-corp-login", name="ACME")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        email="slug_login@example.com",
        hashed_password=hash_password("pass1234!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.close()

    r = client.post(
        "/auth/login",
        json={"email": "slug_login@example.com", "password": "pass1234!", "tenant_slug": "acme-corp-login"},
    )
    assert r.status_code == 200


def test_login_with_invalid_tenant_slug_returns_401(client: TestClient) -> None:
    r = client.post(
        "/auth/login",
        json={"email": "x@x.com", "password": "pass1234!", "tenant_slug": "nonexistent-slug"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


def test_register_returns_201(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    r = client.post(
        "/auth/register",
        json={
            "email": "reg01@example.com",
            "password": "pass1234!",
            "organization_name": "Reg Org 01",
            "tenant_slug": "reg-org-01",
        },
    )
    assert r.status_code == 201


def test_register_response_has_tokens(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    r = client.post(
        "/auth/register",
        json={
            "email": "reg02@example.com",
            "password": "pass1234!",
            "organization_name": "Reg Org 02",
            "tenant_slug": "reg-org-02",
        },
    )
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_register_response_has_user_with_admin_role(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    r = client.post(
        "/auth/register",
        json={
            "email": "reg03@example.com",
            "password": "pass1234!",
            "organization_name": "Reg Org 03",
            "tenant_slug": "reg-org-03",
        },
    )
    assert r.json()["user"]["role"] == "admin"


def test_register_duplicate_slug_returns_409(client: TestClient) -> None:
    slug = "dup-slug-test"
    client.post(
        "/auth/register",
        json={
            "email": "dup01@example.com",
            "password": "pass1234!",
            "organization_name": "Dup Org",
            "tenant_slug": slug,
        },
    )
    r = client.post(
        "/auth/register",
        json={
            "email": "dup02@example.com",
            "password": "pass1234!",
            "organization_name": "Dup Org 2",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 409


def test_register_invalid_slug_pattern_returns_422(client: TestClient) -> None:
    r = client.post(
        "/auth/register",
        json={
            "email": "bad@example.com",
            "password": "pass1234!",
            "organization_name": "Bad Slug Org",
            "tenant_slug": "UPPERCASE",
        },
    )
    assert r.status_code == 422


def test_register_short_password_returns_422(client: TestClient) -> None:
    r = client.post(
        "/auth/register",
        json={
            "email": "x@x.com",
            "password": "short",
            "organization_name": "Org",
            "tenant_slug": "org-short",
        },
    )
    assert r.status_code == 422


def test_register_missing_org_name_returns_422(client: TestClient) -> None:
    r = client.post(
        "/auth/register",
        json={"email": "x@x.com", "password": "pass1234!", "tenant_slug": "no-org"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def test_refresh_returns_401_on_invalid_token(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.getdel.return_value = None  # token not found
    r = client.post("/auth/refresh", json={"refresh_token": "invalid-token"})
    assert r.status_code == 401


def test_refresh_returns_new_access_token(client: TestClient, mock_redis_module: MagicMock) -> None:
    import json as _json

    _, user = _seed_tenant_and_user(email="refresh_user@example.com", password="pass1234!")
    mock_redis_module.getdel.return_value = _json.dumps(
        {"user_id": str(user.id), "tenant_id": str(user.tenant_id), "role": "admin"}
    ).encode()
    mock_redis_module.setex.return_value = True

    r = client.post("/auth/refresh", json={"refresh_token": "some-refresh-token"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["access_token"]


def test_refresh_returns_new_refresh_token(client: TestClient, mock_redis_module: MagicMock) -> None:
    import json as _json

    _, user = _seed_tenant_and_user(email="refresh_rt@example.com", password="pass1234!")
    mock_redis_module.getdel.return_value = _json.dumps(
        {"user_id": str(user.id), "tenant_id": str(user.tenant_id), "role": "admin"}
    ).encode()
    mock_redis_module.setex.return_value = True

    r = client.post("/auth/refresh", json={"refresh_token": "old-refresh"})
    body = r.json()
    assert "refresh_token" in body


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


def test_logout_without_auth_returns_401(client: TestClient) -> None:
    r = client.post("/auth/logout", json={})
    assert r.status_code == 401


def test_logout_returns_204_for_authenticated_user(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    mock_redis_module.exists.return_value = 0

    _, user = _seed_tenant_and_user(email="logout_ok@example.com", password="pass1234!")

    login_r = client.post("/auth/login", json={"email": "logout_ok@example.com", "password": "pass1234!"})
    assert login_r.status_code == 200
    token = login_r.json()["access_token"]

    r = client.post(
        "/auth/logout",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


def test_me_returns_401_without_token(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_user_profile(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    mock_redis_module.exists.return_value = 0

    _, user = _seed_tenant_and_user(email="me_user@example.com", password="pass1234!")

    login_r = client.post("/auth/login", json={"email": "me_user@example.com", "password": "pass1234!"})
    token = login_r.json()["access_token"]

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "me_user@example.com"


def test_me_response_has_role(client: TestClient, mock_redis_module: MagicMock) -> None:
    mock_redis_module.setex.return_value = True
    mock_redis_module.exists.return_value = 0

    _seed_tenant_and_user(email="me_role@example.com", password="pass1234!", role=UserRole.ADMIN)

    login_r = client.post("/auth/login", json={"email": "me_role@example.com", "password": "pass1234!"})
    token = login_r.json()["access_token"]

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["role"] == "admin"
