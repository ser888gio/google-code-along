"""
Task 6.1 — Unit tests for the RS compilation logic (generation/compiler.py).

These tests verify that compile_rs_from_session correctly extracts the
RS document from mock session history without hitting any external services.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from generation.compiler import RS_MARKER, compile_rs_from_session

# ---------------------------------------------------------------------------
# Helpers to build mock session objects
# ---------------------------------------------------------------------------


def _make_part(text: str):
    part = MagicMock()
    part.text = text
    return part


def _make_event(role: str, text: str):
    """Build a minimal mock ADK event with a single text part."""
    event = MagicMock()
    event.content = MagicMock()
    event.content.role = role
    event.content.parts = [_make_part(text)]
    return event


def _make_session(events: list):
    session = MagicMock()
    session.events = events
    return session


def _make_session_service(session):
    """Return an async mock session service that returns the given session."""
    svc = MagicMock()
    svc.get_session = AsyncMock(return_value=session)
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_none_when_session_not_found():
    """compile_rs_from_session returns None when session does not exist."""
    svc = MagicMock()
    svc.get_session = AsyncMock(return_value=None)

    result = await compile_rs_from_session(
        session_service=svc,
        app_name="app",
        user_id="user",
        session_id="missing-session",
    )

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_marker_in_history():
    """compile_rs_from_session returns None when no [GENERATE_RS] marker exists."""
    events = [
        _make_event("user", "Hello, I need a system for sales reports."),
        _make_event("model", "Welcome! Let's start. What is the current state?"),
        _make_event("user", "We do everything manually."),
        _make_event("model", "I see. What would the ideal future look like?"),
    ]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is None


@pytest.mark.asyncio
async def test_extracts_rs_body_after_marker():
    """compile_rs_from_session returns the text after [GENERATE_RS]."""
    rs_document = "# Requirement Specification\n\n## 1. Overview\nThis is the doc."
    model_reply = f"Great, generating now.\n\n{RS_MARKER}\n{rs_document}"

    events = [
        _make_event("user", "Please generate the document."),
        _make_event("model", model_reply),
    ]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is not None
    assert "# Requirement Specification" in result
    assert "## 1. Overview" in result
    assert RS_MARKER not in result


@pytest.mark.asyncio
async def test_strips_leading_whitespace_from_rs_body():
    """The returned RS body has no leading/trailing whitespace."""
    rs_document = "  # RS Title  \n\nSome content."
    model_reply = f"{RS_MARKER}\n{rs_document}"

    events = [_make_event("model", model_reply)]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result == rs_document.strip()


@pytest.mark.asyncio
async def test_returns_most_recent_rs_when_multiple_generations():
    """When [GENERATE_RS] appears multiple times, the most recent one is returned."""
    first_rs = "# First Version\n\nOld content."
    second_rs = "# Second Version\n\nUpdated content."

    events = [
        _make_event("user", "Generate."),
        _make_event("model", f"{RS_MARKER}\n{first_rs}"),
        _make_event("user", "Please add the security section."),
        _make_event("model", f"{RS_MARKER}\n{second_rs}"),
    ]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is not None
    assert "Second Version" in result
    assert "First Version" not in result


@pytest.mark.asyncio
async def test_ignores_user_messages_containing_marker():
    """The marker in a user message is ignored — only model messages are scanned."""
    events = [
        _make_event("user", f"What does {RS_MARKER} mean?"),
        _make_event("model", "That marker triggers document generation."),
    ]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_for_empty_event_list():
    """compile_rs_from_session handles an empty event list gracefully."""
    session = _make_session([])
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is None


@pytest.mark.asyncio
async def test_handles_event_with_no_content():
    """Events without content (tool calls, etc.) are skipped without error."""
    good_event = _make_event("model", f"{RS_MARKER}\n# Valid RS")
    bad_event = MagicMock()
    bad_event.content = None  # no content

    events = [bad_event, good_event]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is not None
    assert "Valid RS" in result


@pytest.mark.asyncio
async def test_full_rs_sections_are_preserved():
    """All standard RS sections are present in the extracted document."""
    rs_sections = """# Requirement Specification — Sales Report System

## 1. Executive Summary
Automate daily sales reporting.

## 2. Current State (As-Is)
Manual process taking 2 hours per day.

## 3. Desired State (To-Be)
Automated pipeline delivering reports by 07:00 CET.

## 4. Scope
### In Scope
- Salesforce integration
- PDF generation

### Out of Scope
- Mobile app

## 5. Functional Requirements
FR-001: Connect to Salesforce API
FR-002: Generate PDF report

## 6. Non-Functional Requirements
NFR-001: Report generation under 3 minutes
NFR-002: 99% availability on business days

## 7. Assumptions & Constraints
- Salesforce sandbox available for testing

## 8. Open Questions
- Who approves the template design?
"""
    model_reply = f"Here is your document.\n\n{RS_MARKER}\n{rs_sections}"
    events = [_make_event("model", model_reply)]
    session = _make_session(events)
    svc = _make_session_service(session)

    result = await compile_rs_from_session(session_service=svc, app_name="app", user_id="user", session_id="s1")

    assert result is not None
    for section in [
        "Executive Summary",
        "Current State",
        "Desired State",
        "Scope",
        "Functional Requirements",
        "Non-Functional Requirements",
        "Assumptions",
        "Open Questions",
        "FR-001",
        "NFR-001",
    ]:
        assert section in result, f"Missing section: {section}"
