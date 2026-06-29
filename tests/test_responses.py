"""Unit tests for uniform response envelopes (app.common.responses).

Verifies:
* Message and Created Pydantic models serialize correctly.
* ok() convenience factory returns the expected envelope.

No database or network access required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.common.responses import Created, Message, ok


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


def test_message_carries_detail_string() -> None:
    m = Message(detail="All good.")
    assert m.detail == "All good."


def test_message_serialises_to_dict() -> None:
    m = Message(detail="ok")
    assert m.model_dump() == {"detail": "ok"}


def test_message_requires_detail() -> None:
    with pytest.raises(PydanticValidationError):
        Message()  # type: ignore[call-arg]


def test_message_detail_must_be_string() -> None:
    with pytest.raises(PydanticValidationError):
        Message(detail=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Created
# ---------------------------------------------------------------------------


def test_created_carries_detail_and_id() -> None:
    c = Created(detail="Resource created.", id="abc-123")
    assert c.detail == "Resource created."
    assert c.id == "abc-123"


def test_created_id_can_be_uuid() -> None:
    import uuid

    uid = uuid.uuid4()
    c = Created(detail="ok", id=uid)
    assert c.id == uid


def test_created_id_can_be_integer() -> None:
    c = Created(detail="ok", id=42)
    assert c.id == 42


def test_created_serialises_to_dict() -> None:
    c = Created(detail="Created.", id="x1")
    data = c.model_dump()
    assert data["detail"] == "Created."
    assert data["id"] == "x1"


def test_created_requires_detail() -> None:
    with pytest.raises(PydanticValidationError):
        Created(id="x")  # type: ignore[call-arg]


def test_created_requires_id() -> None:
    with pytest.raises(PydanticValidationError):
        Created(detail="ok")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ok() factory
# ---------------------------------------------------------------------------


def test_ok_default_returns_ok_string() -> None:
    result = ok()
    assert isinstance(result, Message)
    assert result.detail == "ok"


def test_ok_custom_message() -> None:
    result = ok("Operation completed successfully.")
    assert result.detail == "Operation completed successfully."


def test_ok_returns_message_instance() -> None:
    assert isinstance(ok(), Message)


def test_ok_empty_string_is_accepted() -> None:
    """ok() must not reject an empty string — callers control the message."""
    result = ok("")
    assert result.detail == ""
