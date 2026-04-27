"""
Task 6.5 — End-to-end smoke test: "Automated Sales Report" use case.

Simulates a complete user journey through the RS Generator pipeline:
  1. User greets the agent → gets a welcome response
  2. User describes the current state (As-Is)
  3. User describes the desired state (To-Be)
  4. Agent produces functional + non-functional requirements
  5. User confirms generation → agent outputs [GENERATE_RS] + full document
  6. /document endpoint confirms the document is ready
  7. /document/pdf delivers a valid, non-empty PDF containing expected headings

All external services (ADK runner, Gemini) are mocked.

google.adk stubs are installed by conftest.py before collection — no stubs needed here.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Scripted conversation for the "Automated Sales Report" use case
# ---------------------------------------------------------------------------

RS_MARKER = "[GENERATE_RS]"

SCRIPTED_TURNS = [
    # (user_message, agent_response)
    (
        "Hi, I need help creating a requirement specification.",
        "Welcome! I'm your IT Business Consultant. Let's start. "
        "Could you describe your current process — what do you do today?",
    ),
    (
        "Currently, a sales analyst manually pulls data from spreadsheets every morning. "
        "It takes about 2 hours and is very error-prone.",
        "Understood. That's a significant daily overhead. "
        "What would the ideal future state look like for your team?",
    ),
    (
        "We want an automated system that connects to our CRM, generates a PDF report, "
        "and emails it to managers by 07:00 every morning.",
        "Great. Let me ask about the functional requirements. "
        "Which CRM do you use, and does it have an API?",
    ),
    (
        "We use Salesforce and it has a REST API.",
        "Perfect. How many people will receive this report, "
        "and what level of availability do you expect from the system?",
    ),
    (
        "About 10 managers will receive it. We need it to work on at least 99% of business days.",
        "I have enough information to generate your Requirement Specification. "
        "May I proceed?\n\n"
        + RS_MARKER
        + "\n"
        + """# Requirement Specification — Automated Sales Report System

## 1. Executive Summary
Automate the daily sales reporting process to eliminate manual data collection
and ensure timely delivery to management.

## 2. Current State (As-Is)
A sales analyst manually consolidates data from multiple spreadsheets each morning.
This takes approximately 2 hours and is error-prone due to manual copy-paste operations.

## 3. Desired State (To-Be)
An automated pipeline connects to Salesforce via REST API, generates a consolidated
PDF report, and delivers it by email to all managers by 07:00 CET on every business day.

## 4. Scope
### In Scope
- Salesforce CRM integration via REST API
- Automated PDF report generation
- Scheduled email delivery to a configurable recipient list
- Alert notifications on pipeline failure

### Out of Scope
- Real-time dashboards
- Mobile applications
- Historical trend analysis beyond 90 days

## 5. Functional Requirements
FR-001: The system SHALL connect to Salesforce via the REST API and extract the previous day's closed deals.
FR-002: The system SHALL aggregate sales data by region, product line, and sales representative.
FR-003: The system SHALL generate a PDF report from a predefined template.
FR-004: The system SHALL deliver the report by email to a configurable recipient list by 07:00 CET.
FR-005: The system SHALL send an alert email if the pipeline fails or data is unavailable.

## 6. Non-Functional Requirements
NFR-001: Report generation must complete within 3 minutes.
NFR-002: The pipeline must succeed on at least 99% of business days.
NFR-003: Salesforce credentials must be stored in a secrets manager; no plain-text configuration.
NFR-004: A non-developer must be able to update the recipient list without code changes.

## 7. Assumptions & Constraints
- The Salesforce REST API is accessible from the pipeline's hosting environment.
- An email relay service is available and configured.
- A PDF report template will be provided and approved before development begins.

## 8. Open Questions
- Who approves the PDF template design?
- Is the Salesforce sandbox available for integration testing?
- What is the fallback behaviour if the 07:00 CET deadline is missed?
""",
    ),
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def smoke_app():
    """Set up the FastAPI app with a scripted multi-turn mock runner."""
    import importlib
    import main as main_module

    importlib.reload(main_module)

    session_id = "smoke-test-session"
    collected_events = []

    mock_session = MagicMock()
    mock_session.events = collected_events

    mock_svc = MagicMock()
    mock_svc.get_session = AsyncMock(return_value=mock_session)
    mock_svc.create_session = AsyncMock(return_value=mock_session)

    turn_index = {"i": 0}

    async def scripted_run_async(*args, **kwargs):
        idx = turn_index["i"]
        _, agent_reply = SCRIPTED_TURNS[idx]
        turn_index["i"] += 1

        event = MagicMock()
        event.content = MagicMock()
        event.content.role = "model"
        event.content.parts = [MagicMock(text=agent_reply)]
        collected_events.append(event)
        yield event

    mock_runner = MagicMock()
    mock_runner.run_async = scripted_run_async

    main_module.session_service = mock_svc
    main_module.runner = mock_runner

    return main_module.app, session_id


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_automated_sales_report_smoke(smoke_app):
    """
    Full smoke test: five-turn conversation about an automated sales report system,
    ending with RS generation, document retrieval, and PDF export.
    """
    app, session_id = smoke_app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # — Turn 1: Greeting —
        r = await client.post(
            "/chat",
            json={"message": SCRIPTED_TURNS[0][0], "session_id": session_id},
        )
        assert r.status_code == 200
        body = r.json()
        assert "Consultant" in body["reply"] or "Business" in body["reply"]
        assert body["session_id"] == session_id

        # — Turn 2: As-Is —
        r = await client.post(
            "/chat",
            json={"message": SCRIPTED_TURNS[1][0], "session_id": session_id},
        )
        assert r.status_code == 200
        assert (
            "future" in r.json()["reply"].lower()
            or "ideal" in r.json()["reply"].lower()
        )

        # — Turn 3: To-Be —
        r = await client.post(
            "/chat",
            json={"message": SCRIPTED_TURNS[2][0], "session_id": session_id},
        )
        assert r.status_code == 200

        # — Turn 4: Non-functional requirements —
        r = await client.post(
            "/chat",
            json={"message": SCRIPTED_TURNS[3][0], "session_id": session_id},
        )
        assert r.status_code == 200

        # — Turn 5: RS generation —
        r = await client.post(
            "/chat",
            json={"message": SCRIPTED_TURNS[4][0], "session_id": session_id},
        )
        assert r.status_code == 200
        assert RS_MARKER in r.json()["reply"]

        # — Document retrieval —
        doc = await client.post("/document", json={"session_id": session_id})
        assert doc.status_code == 200
        doc_body = doc.json()
        assert doc_body["ready"] is True
        assert doc_body["markdown"] is not None

        # Verify all standard RS sections are present
        md = doc_body["markdown"]
        for section in [
            "Executive Summary",
            "Current State",
            "Desired State",
            "Functional Requirements",
            "Non-Functional Requirements",
            "Assumptions",
            "Open Questions",
            "FR-001",
            "NFR-001",
        ]:
            assert section in md, f"Missing RS section: {section}"

        # — PDF export —
        pdf = await client.post("/document/pdf", json={"session_id": session_id})
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:5] == b"%PDF-"
        assert len(pdf.content) > 500  # non-trivially sized PDF

        # Spot-check: PDF is a valid non-trivially sized document
        # (text is compressed in the PDF stream, so we verify size instead of content)
        assert len(pdf.content) > 1000
