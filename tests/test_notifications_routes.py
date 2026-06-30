"""Integration tests for Notifications API routes (SQLite TestClient)."""

from __future__ import annotations

import types
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes.notifications import router as notifications_router
from app.core.exceptions import install_exception_handlers
from app.core.security import get_current_user
from app.db.session import get_session
from app.models.enums import UserRole
from notifications_sqlite import make_engine, seed_tenant_user

_TENANT = uuid.uuid4()
_USER = uuid.uuid4()

_engine = make_engine()
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
_ROLE = {"role": UserRole.ADMIN}


def _sess() -> Iterator:
    s = _TestSession()
    try:
        yield s
    finally:
        s.close()


def _user():
    return types.SimpleNamespace(id=_USER, tenant_id=_TENANT, role=_ROLE["role"], is_active=True)


@pytest.fixture(scope="module")
def client():
    seed_tenant_user(_TestSession, tenant_id=_TENANT, user_id=_USER)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(notifications_router)
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True, scope="module")
def patch_ctx():
    with (
        patch("app.services.notification_service.get_current_tenant", return_value=_TENANT),
        patch("app.services.notification_service.get_current_user_id", return_value=_USER),
        patch("app.services.notification_service.EventStoreRepository", autospec=True) as M,
    ):
        M.return_value.next_aggregate_version.return_value = 1
        M.return_value.append.return_value = None
        yield


# --- templates ---


def _create_template(client, **ov) -> dict:
    body = {"template_code": f"tpl-{uuid.uuid4().hex[:6]}", "name": "T", "channel": "in_app",
            "body_template": "Hi {name}"}
    body.update(ov)
    r = client.post("/notifications/templates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_template_lifecycle(client):
    tid = _create_template(client, event_type="ClaimCreated")["id"]
    assert client.post(f"/notifications/templates/{tid}/deactivate").json()["active"] is False
    assert client.post(f"/notifications/templates/{tid}/activate").json()["active"] is True
    assert client.get(f"/notifications/templates/{tid}").status_code == 200


def test_template_search_before_id(client):
    _create_template(client, template_code="tpl-SRCH")
    r = client.get("/notifications/templates/search?q=tpl-SRCH")
    assert r.status_code == 200
    assert any(t["template_code"] == "tpl-SRCH" for t in r.json()["items"])


def test_template_delete_restore(client):
    tid = _create_template(client)["id"]
    assert client.delete(f"/notifications/templates/{tid}").status_code == 204
    assert client.get(f"/notifications/templates/{tid}").status_code == 404
    assert client.post(f"/notifications/templates/{tid}/restore").status_code == 200


def test_template_invalid_language_422(client):
    r = client.post("/notifications/templates", json={"template_code": "bad-lang", "name": "T",
                                                      "channel": "in_app", "body_template": "x", "language": "english"})
    assert r.status_code == 422


# --- notifications ---


def _create_notification(client, **ov) -> dict:
    body = {"channel": "in_app", "recipient_user_id": str(_USER), "body": "Hello"}
    body.update(ov)
    r = client.post("/notifications", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_notification_create_send_read(client):
    nid = _create_notification(client)["id"]
    assert client.post(f"/notifications/{nid}/send").json()["status"] == "sent"
    assert client.post(f"/notifications/{nid}/read").json()["status"] == "read"
    attempts = client.get(f"/notifications/{nid}/attempts").json()
    assert len(attempts) == 1 and attempts[0]["status"] == "succeeded"


def test_notification_requires_recipient_422(client):
    r = client.post("/notifications", json={"channel": "in_app", "body": "x"})
    assert r.status_code == 422


def test_notification_invalid_email_422(client):
    r = client.post("/notifications", json={"channel": "email", "recipient_email": "not-an-email", "body": "x"})
    assert r.status_code == 422


def test_notification_search_and_unread_before_id(client):
    _create_notification(client, body="findme")
    assert client.get("/notifications/search?q=findme").status_code == 200
    assert client.get("/notifications/unread").status_code == 200


def test_notification_invalid_sort_422(client):
    assert client.get("/notifications?sort_by=ssn").status_code == 422


def test_email_notification_send_failed(client):
    nid = _create_notification(client, channel="email", recipient_email="a@b.com", recipient_user_id=None)["id"]
    sent = client.post(f"/notifications/{nid}/send")
    assert sent.status_code == 200 and sent.json()["status"] == "failed"
    retried = client.post(f"/notifications/{nid}/retry")
    assert retried.json()["status"] == "failed" and retried.json()["retry_count"] == 2


def test_cancel_notification(client):
    nid = _create_notification(client)["id"]
    assert client.post(f"/notifications/{nid}/cancel", json={"reason": "dupe"}).json()["status"] == "cancelled"


# --- RBAC ---


def test_rbac_client_cannot_create_template(client):
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.post("/notifications/templates", json={"template_code": "x", "name": "x",
                                                             "channel": "in_app", "body_template": "x"}).status_code == 403
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_rbac_client_can_read_and_mark_read(client):
    _ROLE["role"] = UserRole.ADMIN
    nid = _create_notification(client)["id"]
    client.post(f"/notifications/{nid}/send")
    _ROLE["role"] = UserRole.CLIENT
    try:
        assert client.get("/notifications").status_code == 200
        # _USER is the current user and the recipient -> allowed
        assert client.post(f"/notifications/{nid}/read").status_code == 200
    finally:
        _ROLE["role"] = UserRole.ADMIN


# --- M1: per-user read scoping for CLIENT/DRIVER ---


def _create_for_other(client):
    """Create a notification addressed to a *different* user (as ADMIN)."""
    other = uuid.uuid4()
    r = client.post("/notifications", json={"channel": "in_app", "recipient_email": f"{other.hex[:6]}@x.test",
                                            "body": "for someone else"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("role", [UserRole.CLIENT, UserRole.DRIVER])
def test_non_privileged_cannot_read_others_notification(client, role):
    _ROLE["role"] = UserRole.ADMIN
    nid = _create_for_other(client)  # not addressed to _USER
    _ROLE["role"] = role
    try:
        assert client.get(f"/notifications/{nid}").status_code == 404
        assert client.post(f"/notifications/{nid}/read").status_code == 404
    finally:
        _ROLE["role"] = UserRole.ADMIN


@pytest.mark.parametrize("role", [UserRole.CLIENT, UserRole.DRIVER])
def test_non_privileged_list_is_scoped_to_self(client, role):
    _ROLE["role"] = UserRole.ADMIN
    _create_for_other(client)
    _create_notification(client)  # addressed to _USER
    _ROLE["role"] = role
    try:
        items = client.get("/notifications").json()["items"]
        assert items, "expected at least the viewer's own notification"
        assert all(i["recipient_user_id"] == str(_USER) for i in items)
        # cannot widen scope by passing another recipient_user_id
        other_items = client.get(f"/notifications?recipient_user_id={uuid.uuid4()}").json()["items"]
        assert all(i["recipient_user_id"] == str(_USER) for i in other_items)
    finally:
        _ROLE["role"] = UserRole.ADMIN


def test_admin_and_manager_have_tenant_wide_visibility(client):
    _ROLE["role"] = UserRole.ADMIN
    nid = _create_for_other(client)
    for role in (UserRole.ADMIN, UserRole.MANAGER):
        _ROLE["role"] = role
        assert client.get(f"/notifications/{nid}").status_code == 200
    _ROLE["role"] = UserRole.ADMIN


def test_unread_still_works_for_client(client):
    _ROLE["role"] = UserRole.ADMIN
    nid = _create_notification(client)["id"]
    client.post(f"/notifications/{nid}/send")
    _ROLE["role"] = UserRole.CLIENT
    try:
        r = client.get("/notifications/unread")
        assert r.status_code == 200
        assert all(i["recipient_user_id"] == str(_USER) for i in r.json()["items"])
    finally:
        _ROLE["role"] = UserRole.ADMIN
