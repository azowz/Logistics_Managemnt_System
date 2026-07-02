"""Outbound webhook delivery provider port + safe default adapter (Sprint 13).

Mirrors the notification provider pattern: a narrow :class:`WebhookDeliveryProvider`
port and a **no-network default** that never fakes success. Real HTTP delivery lives
behind this port so the service/consumer stay transport-agnostic and fully testable
(tests inject a fake provider that returns deterministic success/failure).
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class WebhookSendResult:
    """Outcome of a single provider send call."""

    succeeded: bool
    http_status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None


@runtime_checkable
class WebhookDeliveryProvider(Protocol):
    """A transport port for delivering a signed webhook payload."""

    name: str

    def send(
        self, *, target_url: str, body: str, headers: dict, timeout_seconds: int
    ) -> WebhookSendResult: ...


class NoNetworkWebhookProvider:
    """Default provider: performs NO network call and never reports success.

    Returns a clear ``provider_not_configured`` failure so a delivery attempt is
    recorded and the delivery is marked failed — no silent success, no outbound call
    unless a real provider is explicitly configured.
    """

    name = "no_network"

    def send(
        self, *, target_url: str, body: str, headers: dict, timeout_seconds: int
    ) -> WebhookSendResult:
        return WebhookSendResult(
            succeeded=False,
            error_code="provider_not_configured",
            error_message="No webhook delivery provider is configured; delivery skipped.",
        )


class HttpWebhookProvider:
    """Real HTTP webhook provider (httpx). POSTs the signed JSON body to the target URL.

    Timeout-bounded and side-effect-safe: it performs **no internal retry** (retry belongs
    to the service/sweep worker), never logs or returns the signing secret, and truncates
    response bodies. 2xx → success; 4xx/5xx → failure; timeout / connection error →
    failure with a stable ``error_code``. An httpx client can be injected for tests
    (e.g. with a ``MockTransport``) so no real network call is made.
    """

    name = "http"
    _MAX_BODY = 2048

    def __init__(self, *, user_agent: str = "Mesaar-Webhooks/1.0", client=None) -> None:
        self._user_agent = user_agent
        self._client = client  # injectable httpx.Client for tests

    def send(
        self, *, target_url: str, body: str, headers: dict, timeout_seconds: int
    ) -> WebhookSendResult:
        import httpx  # local import keeps httpx off the hot import path

        merged = {**(headers or {}), "User-Agent": self._user_agent}
        started = perf_counter()
        client = self._client or httpx.Client(timeout=float(timeout_seconds or 10))
        owns_client = self._client is None
        try:
            resp = client.post(target_url, content=body.encode("utf-8"), headers=merged)
        except httpx.TimeoutException as exc:
            return WebhookSendResult(
                succeeded=False,
                error_code="timeout",
                error_message=str(exc)[:512],
                duration_ms=_elapsed_ms(started),
            )
        except httpx.HTTPError as exc:  # connection/transport errors, invalid URL, etc.
            return WebhookSendResult(
                succeeded=False,
                error_code="connection_error",
                error_message=str(exc)[:512],
                duration_ms=_elapsed_ms(started),
            )
        finally:
            if owns_client:
                client.close()

        duration = _elapsed_ms(started)
        text = (resp.text or "")[: self._MAX_BODY]
        if 200 <= resp.status_code < 300:
            return WebhookSendResult(
                succeeded=True,
                http_status_code=resp.status_code,
                response_body=text,
                duration_ms=duration,
            )
        return WebhookSendResult(
            succeeded=False,
            http_status_code=resp.status_code,
            response_body=text,
            error_code=f"http_{resp.status_code}",
            error_message=f"HTTP {resp.status_code}",
            duration_ms=duration,
        )


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


_default_provider: WebhookDeliveryProvider = NoNetworkWebhookProvider()


def get_webhook_provider() -> WebhookDeliveryProvider:
    """Return the process-wide webhook delivery provider (DI seam / test override)."""
    return _default_provider


def set_webhook_provider(provider: WebhookDeliveryProvider) -> None:
    """Override the process-wide provider (used by real deployments/tests)."""
    global _default_provider
    _default_provider = provider


__all__ = [
    "WebhookSendResult",
    "WebhookDeliveryProvider",
    "NoNetworkWebhookProvider",
    "HttpWebhookProvider",
    "get_webhook_provider",
    "set_webhook_provider",
]
