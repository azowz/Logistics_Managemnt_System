"""Channel provider ports + adapters (context #19, Sprint 10).

A provider knows how to deliver a single :class:`~app.models.notification.Notification`
over one channel. The **in-app** provider is fully implemented (in-app delivery is
persistence + read-tracking, so "send" succeeds synchronously). Email / SMS / push
/ webhook ship as **null adapters**: they are *not configured* by default and must
never pretend to succeed — they return a ``skipped`` result with a clear reason so
the caller records a delivery attempt rather than silently dropping the message.

No external/paid vendor SDK is imported or hardcoded. Real adapters are wired in
later by replacing the null adapter for a channel in :data:`DEFAULT_PROVIDERS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from app.models.enums import DeliveryAttemptStatus, NotificationChannel


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Outcome of a single provider send call."""

    status: DeliveryAttemptStatus
    provider: str
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    response_payload: Optional[dict] = None

    @property
    def succeeded(self) -> bool:
        return self.status == DeliveryAttemptStatus.SUCCEEDED


@runtime_checkable
class NotificationProvider(Protocol):
    """A channel delivery port."""

    channel: NotificationChannel
    name: str

    def is_configured(self) -> bool:
        ...

    def send(self, notification) -> DeliveryResult:  # noqa: ANN001
        ...


class InAppNotificationProvider:
    """Fully-implemented in-app provider.

    In-app delivery is the persistence of the notification row plus read
    tracking, so a send always succeeds without any external call.
    """

    channel = NotificationChannel.IN_APP
    name = "in_app"

    def is_configured(self) -> bool:
        return True

    def send(self, notification) -> DeliveryResult:  # noqa: ANN001
        return DeliveryResult(
            status=DeliveryAttemptStatus.SUCCEEDED,
            provider=self.name,
            provider_message_id=str(notification.id),
        )


class _NullProvider:
    """Safe placeholder for a channel with no configured external provider.

    Never reports success. Returns ``skipped`` with a clear reason so the caller
    persists a delivery attempt and marks the notification failed — no silent
    success, no network call.
    """

    channel: NotificationChannel
    name: str

    def is_configured(self) -> bool:
        return False

    def send(self, notification) -> DeliveryResult:  # noqa: ANN001
        return DeliveryResult(
            status=DeliveryAttemptStatus.SKIPPED,
            provider=self.name,
            error_code="provider_not_configured",
            error_message=f"No {self.channel.value} provider is configured; delivery skipped.",
        )


class EmailNotificationProvider(_NullProvider):
    channel = NotificationChannel.EMAIL
    name = "email_null"


class SmsNotificationProvider(_NullProvider):
    channel = NotificationChannel.SMS
    name = "sms_null"


class PushNotificationProvider(_NullProvider):
    channel = NotificationChannel.PUSH
    name = "push_null"


class WebhookNotificationProvider(_NullProvider):
    channel = NotificationChannel.WEBHOOK
    name = "webhook_null"


# Process-wide channel → provider registry. Swap a null adapter for a real one
# here (or via ProviderRegistry.register) when a vendor integration ships.
class ProviderRegistry:
    """Resolves a provider for a channel; defaults to the built-in adapters."""

    def __init__(self, providers: Optional[dict] = None) -> None:
        # ``None`` → built-in defaults; an explicit dict (even empty) is honoured.
        if providers is None:
            providers = {
                NotificationChannel.IN_APP: InAppNotificationProvider(),
                NotificationChannel.EMAIL: EmailNotificationProvider(),
                NotificationChannel.SMS: SmsNotificationProvider(),
                NotificationChannel.PUSH: PushNotificationProvider(),
                NotificationChannel.WEBHOOK: WebhookNotificationProvider(),
            }
        self._providers: dict = providers

    def register(self, provider: NotificationProvider) -> None:
        self._providers[provider.channel] = provider

    def get(self, channel: NotificationChannel) -> Optional[NotificationProvider]:
        return self._providers.get(channel)


default_provider_registry = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    """Return the process-wide provider registry (DI seam / test override)."""
    return default_provider_registry


__all__ = [
    "DeliveryResult",
    "NotificationProvider",
    "InAppNotificationProvider",
    "EmailNotificationProvider",
    "SmsNotificationProvider",
    "PushNotificationProvider",
    "WebhookNotificationProvider",
    "ProviderRegistry",
    "default_provider_registry",
    "get_provider_registry",
]
