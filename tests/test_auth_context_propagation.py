"""Regression: the tenant/user bound by authentication must reach the endpoint.

FastAPI runs *sync* dependencies in a threadpool, inside a copy of the request
context, so a ``ContextVar.set()`` made there is discarded when the dependency
returns. The authenticated tenant (token ``tid`` / API-key tenant) and acting user
must nevertheless be visible to the endpoint and every service it calls — that is
what scopes ``tenant_id`` writes, RLS GUCs on later transactions, and audit
attribution. A client-supplied ``X-Tenant-ID`` header must never override them.
"""

from __future__ import annotations

import uuid
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.middleware.request_context import RequestContextMiddleware
from app.core.security import create_access_token, get_current_user, hash_password
from app.db.base import Base
from app.db.session import get_session
from app.db.tenant import get_current_tenant, get_current_user_id
from app.integrations.auth import AuthenticatedPartner, require_api_key_scopes
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import User
from app.services.integration_service import ApiKeyAuthContext

_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
_TABLES = [Tenant.__table__, User.__table__]

_TENANT = uuid.uuid4()
_SPOOFED_TENANT = uuid.uuid4()
_USER = uuid.uuid4()


def _session() -> Generator[Session, None, None]:
    s = _Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="module", autouse=True)
def _db():
    Base.metadata.create_all(_engine, tables=_TABLES)
    s = _Session()
    s.add(Tenant(id=_TENANT, slug="ctx-tenant", name="Ctx", status="active"))
    s.add(
        User(
            id=_USER,
            tenant_id=_TENANT,
            email="ctx@example.com",
            hashed_password=hash_password("x" * 12),
            role=UserRole.MANAGER,
            is_active=True,
        )
    )
    s.commit()
    s.close()
    yield
    Base.metadata.drop_all(_engine, tables=_TABLES)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.dependency_overrides[get_session] = _session

    @app.get("/sync-endpoint")
    def sync_endpoint(_: User = Depends(get_current_user)) -> dict:
        return {"tenant": str(get_current_tenant()), "user": str(get_current_user_id())}

    @app.get("/async-endpoint")
    async def async_endpoint(_: User = Depends(get_current_user)) -> dict:
        return {"tenant": str(get_current_tenant()), "user": str(get_current_user_id())}

    @app.get("/partner-endpoint")
    async def partner_endpoint(
        _: AuthenticatedPartner = Depends(require_api_key_scopes()),
    ) -> dict:
        return {"tenant": str(get_current_tenant()), "user": str(get_current_user_id())}

    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    redis = MagicMock()
    redis.exists.return_value = 0
    with patch("app.core.security.get_redis", return_value=redis):
        yield TestClient(_app())


def _token() -> str:
    return create_access_token(
        subject=str(_USER), role=UserRole.MANAGER.value, tenant_id=str(_TENANT)
    )


@pytest.mark.parametrize("path", ["/sync-endpoint", "/async-endpoint"])
def test_jwt_tenant_and_user_reach_endpoint(client: TestClient, path: str) -> None:
    r = client.get(path, headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200, r.text
    assert r.json() == {"tenant": str(_TENANT), "user": str(_USER)}


@pytest.mark.parametrize("path", ["/sync-endpoint", "/async-endpoint"])
def test_tenant_header_cannot_override_token_tenant(client: TestClient, path: str) -> None:
    r = client.get(
        path,
        headers={"Authorization": f"Bearer {_token()}", "X-Tenant-ID": str(_SPOOFED_TENANT)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tenant"] == str(_TENANT)


def test_api_key_tenant_overrides_header(client: TestClient) -> None:
    partner_tenant = uuid.uuid4()
    ctx = ApiKeyAuthContext(
        api_key_id=uuid.uuid4(),
        partner_id=uuid.uuid4(),
        tenant_id=partner_tenant,
        scopes=(),
    )
    with patch(
        "app.integrations.auth.IntegrationService.authenticate_api_key", return_value=ctx
    ), patch("app.integrations.auth.session_scope"):
        r = client.get(
            "/partner-endpoint",
            headers={"Authorization": "Bearer key", "X-Tenant-ID": str(_SPOOFED_TENANT)},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"tenant": str(partner_tenant), "user": "None"}
