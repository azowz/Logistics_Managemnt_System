"""Application error hierarchy and FastAPI exception handlers.

This module defines:

* :class:`AppError` and its HTTP-status-bearing subclasses, the canonical way
  the application signals failures to the API layer.
* :class:`ErrorResponse`, the uniform JSON body returned for every error.
* :func:`install_exception_handlers`, which wires handlers into a FastAPI app
  for :class:`AppError`, FastAPI's :class:`RequestValidationError`, a catch-all
  :class:`Exception`, AND the EXISTING domain exceptions from
  ``app.services.exceptions`` (mapped to appropriate HTTP statuses).

The current request id (when available) is echoed back in every error body to
make client-side and server-side logs correlatable.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.observability.logging import get_logger
from app.repositories.errors import NotFoundError as RepositoryNotFoundError
from app.services.exceptions import (
    AssignmentError,
    CapacityError,
    ConflictError as DomainConflictError,
    DomainError,
    NotFoundError,
    StatusTransitionError,
    TrackingEventError,
    ValidationError,
)

logger = get_logger(__name__)

__all__ = [
    "ErrorDetail",
    "ErrorResponse",
    "AppError",
    "AuthError",
    "ForbiddenError",
    "NotFoundAPIError",
    "ConflictError",
    "UnprocessableError",
    "RateLimitError",
    "InternalError",
    "install_exception_handlers",
]


class ErrorDetail(BaseModel):
    """The ``error`` object embedded in every :class:`ErrorResponse`."""

    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Human-readable error message.")
    details: Any | None = Field(
        default=None, description="Optional structured context (e.g. validation errors)."
    )
    request_id: str | None = Field(
        default=None, description="Correlation id for the originating request, if any."
    )


class ErrorResponse(BaseModel):
    """The uniform JSON envelope returned for every error response."""

    error: ErrorDetail


class AppError(Exception):
    """Base application exception carrying HTTP semantics.

    Attributes:
        status_code: The HTTP status code to return.
        code: A stable machine-readable error code.
        message: A human-readable description.
        details: Optional structured context for the client.
    """

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: Any | None = None,
    ) -> None:
        # Allow per-instance overrides while keeping class-level defaults so
        # subclasses can be raised with zero arguments.
        self.status_code = status_code if status_code is not None else self.status_code
        self.code = code if code is not None else self.code
        self.message = message if message is not None else self.message
        self.details = details
        super().__init__(self.message)


class AuthError(AppError):
    """Authentication failed or credentials are missing/invalid (HTTP 401)."""

    status_code = 401
    code = "unauthorized"
    message = "Authentication is required or has failed."


class ForbiddenError(AppError):
    """The caller is authenticated but lacks permission (HTTP 403)."""

    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class NotFoundAPIError(AppError):
    """A requested resource does not exist (HTTP 404)."""

    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    """The request conflicts with the current resource state (HTTP 409)."""

    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class UnprocessableError(AppError):
    """The request was well-formed but semantically invalid (HTTP 422)."""

    status_code = 422
    code = "unprocessable_entity"
    message = "The request could not be processed."


class RateLimitError(AppError):
    """The caller has exceeded an allowed rate (HTTP 429)."""

    status_code = 429
    code = "rate_limited"
    message = "Too many requests; please retry later."


class InternalError(AppError):
    """An unexpected server-side failure (HTTP 500)."""

    status_code = 500
    code = "internal_error"
    message = "An internal server error occurred."


# Mapping of EXISTING domain exceptions (app.services.exceptions) to the API
# error metadata used to render their responses. Order matters when iterating:
# more specific subclasses must be checked before their base ``DomainError``.
_DOMAIN_ERROR_MAP: tuple[tuple[type[DomainError], int, str], ...] = (
    (NotFoundError, 404, "not_found"),
    (DomainConflictError, 409, "conflict"),
    (CapacityError, 409, "capacity_exceeded"),
    (AssignmentError, 409, "assignment_conflict"),
    (StatusTransitionError, 409, "invalid_status_transition"),
    (TrackingEventError, 422, "invalid_tracking_event"),
    (ValidationError, 422, "validation_error"),
    # DomainError is the catch-all base; keep it LAST so subclasses win.
    (DomainError, 400, "domain_error"),
)


def _get_request_id(request: Request) -> str | None:
    """Best-effort extraction of the current request's correlation id.

    Resolution order:
        1. ``request.state.request_id`` (set by the request-context middleware).
        2. The configured request-id header on the inbound request.

    Never raises; returns ``None`` when no id can be determined.
    """

    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid

    try:
        from app.core.config import get_settings

        header_name = get_settings().request_id_header
    except Exception:  # noqa: BLE001 - settings access must never break error handling
        header_name = "X-Request-ID"

    header_value = request.headers.get(header_name)
    return header_value or None


def _build_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    details: Any | None = None,
) -> JSONResponse:
    """Render an :class:`ErrorResponse` as a :class:`JSONResponse`."""

    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
    )
    # ``mode="json"`` ensures nested values (e.g. UUIDs) are JSON-serializable.
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def install_exception_handlers(app: FastAPI) -> None:
    """Register all application exception handlers on ``app``.

    Handlers are installed for:
        * :class:`AppError` (and subclasses).
        * Each domain exception from ``app.services.exceptions``.
        * FastAPI's :class:`RequestValidationError`.
        * A catch-all :class:`Exception` (logged at error level).

    Args:
        app: The FastAPI application to configure.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = _get_request_id(request)
        # 5xx are genuine server faults; 4xx are expected client-side issues.
        log = logger.bind(request_id=request_id, error_code=exc.code)
        if exc.status_code >= 500:
            log.opt(exception=exc).error(
                "Unhandled application error: {} ({})", exc.message, exc.status_code
            )
        else:
            log.warning(
                "Application error: {} ({} {})", exc.message, exc.status_code, exc.code
            )
        return _build_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            details=exc.details,
        )

    @app.exception_handler(DomainError)
    async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        request_id = _get_request_id(request)
        # Resolve the most specific mapping for this domain exception type.
        status_code, code = 400, "domain_error"
        for exc_type, mapped_status, mapped_code in _DOMAIN_ERROR_MAP:
            if isinstance(exc, exc_type):
                status_code, code = mapped_status, mapped_code
                break

        message = str(exc) or code.replace("_", " ").capitalize()
        log = logger.bind(request_id=request_id, error_code=code)
        if status_code >= 500:
            log.opt(exception=exc).error("Domain error: {}", message)
        else:
            log.info("Domain error: {} ({} {})", message, status_code, code)
        return _build_response(
            status_code=status_code,
            code=code,
            message=message,
            request_id=request_id,
        )

    @app.exception_handler(RepositoryNotFoundError)
    async def _handle_repository_not_found(
        request: Request, exc: RepositoryNotFoundError
    ) -> JSONResponse:
        # Repository-layer "not found" is a distinct hierarchy from the domain
        # NotFoundError; both map to HTTP 404 at the API boundary.
        request_id = _get_request_id(request)
        message = str(exc) or "The requested resource was not found."
        logger.bind(request_id=request_id, error_code="not_found").info(
            "Not found: {}", message
        )
        return _build_response(
            status_code=404,
            code="not_found",
            message=message,
            request_id=request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.bind(request_id=request_id).info(
            "Request validation failed: {} error(s)", len(exc.errors())
        )
        # ``exc.errors()`` may contain non-JSON-native objects (bytes, nested
        # exceptions); coerce them so the response body is serializable.
        return _build_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            request_id=request_id,
            details=_jsonable(exc.errors()),
        )

    @app.exception_handler(PydanticValidationError)
    async def _handle_pydantic_validation_error(
        request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        # Raised when a handler constructs a Pydantic model directly (e.g. a
        # ``*ListParams`` from query args). Surface as a 422 like request-body
        # validation rather than a 500.
        request_id = _get_request_id(request)
        logger.bind(request_id=request_id).info(
            "Model validation failed: {} error(s)", len(exc.errors())
        )
        return _build_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            request_id=request_id,
            details=_jsonable(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.bind(request_id=request_id).opt(exception=exc).error(
            "Unhandled exception: {}", exc.__class__.__name__
        )
        return _build_response(
            status_code=500,
            code="internal_error",
            message="An internal server error occurred.",
            request_id=request_id,
        )

    logger.debug("Exception handlers installed.")


def _jsonable(value: Any) -> Any:
    """Best-effort coercion of ``value`` into JSON-serializable primitives.

    FastAPI's validation error details can include ``bytes``, exceptions, and
    other non-serializable objects in their ``ctx``; this walks the structure
    and stringifies anything that is not natively serializable.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)
