"""Tests for the notification state machine + template renderer (Sprint 10)."""

from __future__ import annotations

import pytest

from app.models.enums import NotificationStatus
from app.services.exceptions import StatusTransitionError, ValidationError
from app.services.notification_policies import NotificationStateMachine, TemplateRenderer


# --- state machine --------------------------------------------------------


def test_happy_path_transitions():
    assert NotificationStateMachine.can_transition(NotificationStatus.PENDING, NotificationStatus.QUEUED)
    assert NotificationStateMachine.can_transition(NotificationStatus.QUEUED, NotificationStatus.SENT)
    assert NotificationStateMachine.can_transition(NotificationStatus.SENT, NotificationStatus.READ)
    assert NotificationStateMachine.can_transition(NotificationStatus.FAILED, NotificationStatus.QUEUED)
    assert NotificationStateMachine.can_transition(NotificationStatus.PENDING, NotificationStatus.SENT)


@pytest.mark.parametrize("terminal", [NotificationStatus.CANCELLED, NotificationStatus.READ])
def test_terminal_states(terminal):
    assert NotificationStateMachine.is_terminal(terminal)
    assert not NotificationStateMachine.ALLOWED_TRANSITIONS[terminal]


def test_illegal_transitions_raise():
    with pytest.raises(StatusTransitionError):
        NotificationStateMachine.validate_transition(NotificationStatus.READ, NotificationStatus.SENT)
    with pytest.raises(StatusTransitionError):
        NotificationStateMachine.validate_transition(NotificationStatus.CANCELLED, NotificationStatus.QUEUED)


# --- renderer -------------------------------------------------------------


def test_render_substitutes_variables():
    assert TemplateRenderer.render("Hi {name}, ref {ref}", {"name": "Sam", "ref": "S1"}) == "Hi Sam, ref S1"


def test_render_leaves_unknown_placeholders_intact():
    assert TemplateRenderer.render("Hi {who}", {}) == "Hi {who}"


def test_render_none_is_empty():
    assert TemplateRenderer.render(None, {"a": 1}) == ""


def test_required_variables_validation():
    schema = {"required": ["name", "ref"]}
    TemplateRenderer.validate_variables(schema, {"name": "x", "ref": "y"})  # no raise
    with pytest.raises(ValidationError):
        TemplateRenderer.validate_variables(schema, {"name": "x"})


def test_required_variables_empty_schema_ok():
    TemplateRenderer.validate_variables(None, {})
    TemplateRenderer.validate_variables({}, {})
    assert TemplateRenderer.required_variables({"required": ["a"]}) == ["a"]


def test_malformed_template_raises():
    with pytest.raises(ValidationError):
        TemplateRenderer.render("Hi {", {})
