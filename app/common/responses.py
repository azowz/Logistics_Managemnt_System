"""Uniform success-response envelopes.

These intentionally tiny models give every endpoint a consistent shape for
"operation succeeded, here is a human-readable note" style responses, without
encoding any business concepts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["Message", "ok", "Created"]


class Message(BaseModel):
    """A simple ``{"detail": "..."}`` envelope for plain OK responses."""

    detail: str = Field(description="Human-readable result message.")


class Created(BaseModel):
    """Envelope returned after creating a resource.

    Carries a message plus the identifier of the newly created entity so that
    callers do not have to parse a ``Location`` header to learn the id.
    """

    detail: str = Field(description="Human-readable result message.")
    id: Any = Field(description="Identifier of the newly created resource.")


def ok(detail: str = "ok") -> Message:
    """Construct a standard :class:`Message` success envelope.

    Args:
        detail: The message to return; defaults to ``"ok"``.

    Returns:
        A :class:`Message` carrying ``detail``.
    """

    return Message(detail=detail)
