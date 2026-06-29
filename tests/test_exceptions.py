"""Unit tests for the application exception hierarchy and FastAPI handlers.

Tests are split into two groups:
* Pure Python tests — exercise the exception classes without a running app.
* FastAPI handler tests — spin up a minimal TestClient to verify that
  install_exception_handlers() wires all handlers correctly and returns the
  expected JSON envelopes.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AppError,
    AuthError,
    ConflictError,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    InternalError,
    NotFoundAPIError,
    RateLimitError,
    UnprocessableError,
    install_exception_handlers,
)
from app.services.exceptions import (
    AssignmentError,
    CapacityError,
    DomainError,
    NotFoundError,
    StatusTransitionError,
    TrackingEventError,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Exception hierarchy — class-level defaults
# ---------------------------------------------------------------------------


def test_app_error_is_exception_subclass() -> None:
    assert issubclass(AppError, Exception)


def test_app_error_default_status_code() -> None:
    assert AppError.status_code == 500


def test_app_error_default_code() -> None:
    assert AppError.code == "internal_error"


def test_auth_error_status_code() -> None:
    assert AuthError.status_code == 401


def test_auth_error_code() -> None:
    assert AuthError.code == "unauthorized"


def test_forbidden_error_status_code() -> None:
    assert ForbiddenError.status_code == 403


def test_not_found_api_error_status_code() -> None:
    assert NotFoundAPIError.status_code == 404


def test_conflict_error_status_code() -> None:
    assert ConflictError.status_code == 409


def test_unprocessable_error_status_code() -> None:
    assert UnprocessableError.status_code == 422


def test_rate_limit_error_status_code() -> None:
    assert RateLimitError.status_code == 429


def test_internal_error_status_code() -> None:
    assert InternalError.status_code == 500


# ---------------------------------------------------------------------------
# AppError — instance construction
# ---------------------------------------------------------------------------


def test_app_error_can_be_raised_with_no_args() -> None:
    with pytest.raises(AppError) as exc_info:
        raise AppError()
    assert exc_info.value.status_code == 500


def test_app_error_message_override() -> None:
    err = AppError("Custom message.")
    assert err.message == "Custom message."


def test_app_error_status_code_override() -> None:
    err = AppError(status_code=418)
    assert err.status_code == 418


def test_app_error_code_override() -> None:
    err = AppError(code="my_custom_code")
    assert err.code == "my_custom_code"


def test_app_error_details_attribute() -> None:
    err = AppError(details={"field": "value"})
    assert err.details == {"field": "value"}


def test_app_error_str_returns_message() -> None:
    err = AppError("Something went wrong.")
    assert str(err) == "Something went wrong."


# ---------------------------------------------------------------------------
# Domain exceptions — hierarchy
# ---------------------------------------------------------------------------


def test_domain_error_is_exception_subclass() -> None:
    assert issubclass(DomainError, Exception)


def test_not_found_error_is_domain_error() -> None:
    assert issubclass(NotFoundError, DomainError)


def test_validation_error_is_domain_error() -> None:
    assert issubclass(ValidationError, DomainError)


def test_capacity_error_is_domain_error() -> None:
    assert issubclass(CapacityError, DomainError)


def test_assignment_error_is_domain_error() -> None:
    assert issubclass(AssignmentError, DomainError)


def test_status_transition_error_is_domain_error() -> None:
    assert issubclass(StatusTransitionError, DomainError)


def test_tracking_event_error_is_domain_error() -> None:
    assert issubclass(TrackingEventError, DomainError)


# ---------------------------------------------------------------------------
# ErrorDetail / ErrorResponse Pydantic models
# ---------------------------------------------------------------------------


def test_error_detail_required_fields() -> None:
    d = ErrorDetail(code="not_found", message="Resource missing.")
    assert d.code == "not_found"
    assert d.message == "Resource missing."
    assert d.details is None
    assert d.request_id is None


def test_error_response_wraps_error_detail() -> None:
    detail = ErrorDetail(code="err", message="msg")
    resp = ErrorResponse(error=detail)
    assert resp.error is detail


def test_error_response_serialises_to_dict() -> None:
    detail = ErrorDetail(code="err", message="msg")
    resp = ErrorResponse(error=detail)
    data = resp.model_dump()
    assert data["error"]["code"] == "err"
    assert data["error"]["message"] == "msg"


# ---------------------------------------------------------------------------
# install_exception_handlers — integration with TestClient
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_app() -> FastAPI:
    """Minimal FastAPI application with all exception handlers installed."""
    from fastapi import Request

    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/app-error")
    def _app_error():
        raise AppError("test app error", status_code=400, code="test_code")

    @app.get("/auth-error")
    def _auth_error():
        raise AuthError()

    @app.get("/forbidden")
    def _forbidden():
        raise ForbiddenError()

    @app.get("/not-found")
    def _not_found():
        raise NotFoundAPIError("Widget not found.")

    @app.get("/conflict")
    def _conflict():
        raise ConflictError()

    @app.get("/domain-not-found")
    def _domain_not_found():
        raise NotFoundError("Domain entity missing.")

    @app.get("/domain-validation")
    def _domain_validation():
        raise ValidationError("Field 'name' is required.")

    @app.get("/domain-transition")
    def _domain_transition():
        raise StatusTransitionError("Cannot cancel a delivered shipment.")

    @app.get("/domain-capacity")
    def _domain_capacity():
        raise CapacityError("Warehouse is full.")

    @app.get("/domain-assignment")
    def _domain_assignment():
        raise AssignmentError("Driver already assigned.")

    @app.get("/validation")
    def _validation_endpoint(x: int):
        return {"x": x}

    @app.get("/ok")
    def _ok():
        return {"status": "ok"}

    return app


@pytest.fixture(scope="module")
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app, raise_server_exceptions=False)


def test_handler_app_error_returns_correct_status(client: TestClient) -> None:
    r = client.get("/app-error")
    assert r.status_code == 400


def test_handler_app_error_returns_error_envelope(client: TestClient) -> None:
    r = client.get("/app-error")
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "test_code"
    assert body["error"]["message"] == "test app error"


def test_handler_auth_error_returns_401(client: TestClient) -> None:
    r = client.get("/auth-error")
    assert r.status_code == 401


def test_handler_auth_error_code_is_unauthorized(client: TestClient) -> None:
    r = client.get("/auth-error")
    assert r.json()["error"]["code"] == "unauthorized"


def test_handler_forbidden_returns_403(client: TestClient) -> None:
    r = client.get("/forbidden")
    assert r.status_code == 403


def test_handler_not_found_returns_404(client: TestClient) -> None:
    r = client.get("/not-found")
    assert r.status_code == 404


def test_handler_not_found_message(client: TestClient) -> None:
    r = client.get("/not-found")
    assert "Widget not found." in r.json()["error"]["message"]


def test_handler_conflict_returns_409(client: TestClient) -> None:
    r = client.get("/conflict")
    assert r.status_code == 409


def test_handler_domain_not_found_returns_404(client: TestClient) -> None:
    r = client.get("/domain-not-found")
    assert r.status_code == 404


def test_handler_domain_not_found_code(client: TestClient) -> None:
    r = client.get("/domain-not-found")
    assert r.json()["error"]["code"] == "not_found"


def test_handler_domain_validation_returns_422(client: TestClient) -> None:
    r = client.get("/domain-validation")
    assert r.status_code == 422


def test_handler_domain_status_transition_returns_409(client: TestClient) -> None:
    r = client.get("/domain-transition")
    assert r.status_code == 409


def test_handler_domain_capacity_returns_409(client: TestClient) -> None:
    r = client.get("/domain-capacity")
    assert r.status_code == 409


def test_handler_domain_assignment_returns_409(client: TestClient) -> None:
    r = client.get("/domain-assignment")
    assert r.status_code == 409


def test_handler_pydantic_validation_error_returns_422(client: TestClient) -> None:
    """Passing a non-integer for ?x should trigger RequestValidationError → 422."""
    r = client.get("/validation", params={"x": "not-an-int"})
    assert r.status_code == 422


def test_handler_pydantic_validation_error_code(client: TestClient) -> None:
    r = client.get("/validation", params={"x": "not-an-int"})
    body = r.json()
    assert body["error"]["code"] == "validation_error"


def test_handler_valid_request_passes_through(client: TestClient) -> None:
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_handler_error_response_has_error_key(client: TestClient) -> None:
    """All error responses must have the top-level 'error' key."""
    for path in ["/app-error", "/auth-error", "/forbidden", "/not-found"]:
        r = client.get(path)
        assert "error" in r.json(), f"Missing 'error' key for {path}"
