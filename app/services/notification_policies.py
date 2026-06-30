"""Notifications domain policies — state machine + template rendering (Sprint 10).

Single source of truth for notification status transitions and for safe,
dependency-free template rendering. No FastAPI, no I/O.

Notification::
    pending → queued → sent
    {pending, queued} → cancelled
    {queued, sent} → failed
    sent → read
    failed → queued      (retry)
  Terminal: cancelled, read.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Mapping

from app.models.enums import NotificationStatus
from app.services.exceptions import StatusTransitionError, ValidationError


class NotificationStateMachine:
    """Validates and describes Notification status transitions."""

    ALLOWED_TRANSITIONS: Dict[NotificationStatus, FrozenSet[NotificationStatus]] = {
        NotificationStatus.PENDING: frozenset(
            {NotificationStatus.QUEUED, NotificationStatus.SENT,
             NotificationStatus.FAILED, NotificationStatus.CANCELLED}
        ),
        NotificationStatus.QUEUED: frozenset(
            {NotificationStatus.SENT, NotificationStatus.FAILED, NotificationStatus.CANCELLED}
        ),
        NotificationStatus.SENT: frozenset({NotificationStatus.READ, NotificationStatus.FAILED}),
        NotificationStatus.FAILED: frozenset({NotificationStatus.QUEUED, NotificationStatus.CANCELLED}),
        # Terminal states.
        NotificationStatus.CANCELLED: frozenset(),
        NotificationStatus.READ: frozenset(),
    }

    TERMINAL_STATES: FrozenSet[NotificationStatus] = frozenset(
        {NotificationStatus.CANCELLED, NotificationStatus.READ}
    )

    @classmethod
    def is_terminal(cls, status: NotificationStatus) -> bool:
        return status in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, current: NotificationStatus, target: NotificationStatus) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: NotificationStatus, target: NotificationStatus) -> None:
        if not cls.can_transition(current, target):
            raise StatusTransitionError(
                f"Cannot transition notification from '{current.value}' to '{target.value}'."
            )


class _SafeDict(dict):
    """``str.format_map`` helper that leaves unknown ``{placeholders}`` intact."""

    def __missing__(self, key):  # noqa: ANN001, ANN204
        return "{" + key + "}"


class TemplateRenderer:
    """Renders subject/body templates with ``{variable}`` placeholders.

    Dependency-free (Python ``str.format_map``). Required variables declared in a
    template's ``variables_schema`` (``{"required": [...]}``) are validated before
    rendering so a misconfigured template fails loudly rather than emitting a
    half-rendered message.
    """

    @staticmethod
    def required_variables(variables_schema: Mapping | None) -> list[str]:
        if not variables_schema:
            return []
        req = variables_schema.get("required") if isinstance(variables_schema, Mapping) else None
        return list(req) if isinstance(req, (list, tuple)) else []

    @classmethod
    def validate_variables(cls, variables_schema: Mapping | None, variables: Mapping) -> None:
        missing = [k for k in cls.required_variables(variables_schema) if k not in (variables or {})]
        if missing:
            raise ValidationError(
                f"Missing required template variable(s): {', '.join(sorted(missing))}."
            )

    @staticmethod
    def render(template: str | None, variables: Mapping | None) -> str:
        if template is None:
            return ""
        try:
            return template.format_map(_SafeDict(variables or {}))
        except (ValueError, IndexError) as exc:
            # Malformed format string (e.g. stray brace) — fail loudly.
            raise ValidationError(f"Template could not be rendered: {exc}") from exc
