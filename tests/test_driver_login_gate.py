"""Driver phone login is disabled in production while OTP verification is a stub."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import driver_self
from app.db.session import get_session


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(driver_self.router)
    app.dependency_overrides[get_session] = lambda: MagicMock()
    return TestClient(app)


def test_driver_login_returns_501_in_production() -> None:
    prod = types.SimpleNamespace(is_production=True, access_token_expire_minutes=60)
    with patch.object(driver_self, "get_settings", return_value=prod), patch.object(
        driver_self, "DriverService"
    ) as service:
        r = _client().post("/auth/driver/login", json={"phone": "+966500000000", "otp": "0000"})
    assert r.status_code == 501
    service.assert_not_called()  # no lookup, no token issued


def test_driver_login_unknown_phone_is_401_outside_production() -> None:
    dev = types.SimpleNamespace(is_production=False, access_token_expire_minutes=60)
    with patch.object(driver_self, "get_settings", return_value=dev), patch.object(
        driver_self, "DriverService"
    ) as service:
        service.return_value.login_by_phone.return_value = None
        r = _client().post("/auth/driver/login", json={"phone": "+966500000000"})
    assert r.status_code == 401
