"""Deployment boundary, browser CORS and API compatibility regression gates."""

import copy
import json

from fastapi.testclient import TestClient

from app.main import create_app
from scripts.check_contract import API_DIR, compatibility_errors


def test_openapi_matches_pre_separation_contract():
    current = create_app().openapi()
    baseline = json.loads((API_DIR / "openapi.v1.baseline.json").read_text(encoding="utf-8"))
    assert compatibility_errors(baseline, current) == []
    assert current == json.loads((API_DIR / "openapi.json").read_text(encoding="utf-8"))


def test_contract_gate_rejects_schema_and_endpoint_breaks():
    baseline = json.loads((API_DIR / "openapi.v1.baseline.json").read_text(encoding="utf-8"))
    changed = copy.deepcopy(baseline)
    del changed["paths"]["/v1/auth/login"]["post"]
    changed["components"]["schemas"]["DriverRead"]["required"] = []
    errors = compatibility_errors(baseline, changed)
    assert any("POST /v1/auth/login" in error for error in errors)
    assert any("DriverRead" in error for error in errors)


def test_browser_preflight_auth_errors_and_request_id(monkeypatch):
    from app.core.config import Settings
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            secret_key="cors-test-secret-key-at-least-32-characters",
            cors_origins=["https://frontend.example.test"],
        ),
    )
    client = TestClient(create_app())
    headers = {"Origin": "https://frontend.example.test", "X-Request-ID": "browser-test"}
    response = client.options(
        "/v1/drivers/me",
        headers={
            **headers,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type,x-request-id",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    denied = client.options(
        "/v1/drivers/me",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    response = client.get("/v1/drivers/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["x-request-id"] == "browser-test"
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    assert client.get("/health/live").status_code == 200
