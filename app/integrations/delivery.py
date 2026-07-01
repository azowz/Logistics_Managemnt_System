"""Outbound webhook delivery provider port + safe default adapter (Sprint 13).

Mirrors the notification provider pattern: a narrow :class:`WebhookDeliveryProvider`
port and a **no-network default** that never fakes success. Real HTTP delivery lives
behind this port so the service/consumer stay transport-agnostic and fully testable
(tests inject a fake provider that returns deterministic success/failure).
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def send(self, *, target_url: str, body: str, headers: dict, timeout_seconds: int) -> WebhookSendResult:
        ...


class NoNetworkWebhookProvider:
    """Default provider: performs NO network call and never reports success.

    Returns a clear ``provider_not_configured`` failure so a delivery attempt is
    recorded and the delivery is marked failed — no silent success, no outbound call
    unless a real provider is explicitly configured.
    """

    name = "no_network"

    def send(self, *, target_url: str, body: str, headers: dict, timeout_seconds: int) -> WebhookSendResult:
        return WebhookSendResult(
            succeeded=False,
            error_code="provider_not_configured",
            error_message="No webhook delivery provider is configured; delivery skipped.",
        )


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
    "get_webhook_provider",
    "set_webhook_provider",
]
