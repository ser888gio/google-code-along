"""
Task 6.2 — Integration tests for the FastAPI agent pipeline (main.py).

The ADK runner and session service are mocked so these tests run without
a live GCP/Vertex AI connection. They verify that:
  - The /health endpoint is reachable
  - /chat returns a well-formed response
  - /chat/stream returns SSE events including session_id, text chunks, and [DONE]
  - /document returns ready=False before a document is generated
  - /document returns the markdown and ready=True after [GENERATE_RS] appears
  - /document/pdf returns a valid PDF when a document is ready
  - /document/pdf returns 404 when no document has been generated

google.adk stubs are installed by conftest.py before collection — no stubs needed here.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RS_MARKER = "[GENERATE_RS]"

SAMPLE_RS_MARKDOWN = """# Requirement Specification — Test Project

## 1. Executive Summary
Automated test project for verifying the RS pipeline.

## 2. Functional Requirements
FR-001: The system shall do something useful.

## 3. Non-Functional Requirements
NFR-001: Performance must be acceptable.
"""


def _make_fake_event(text: str):
    """Build a fake ADK event with a single text part."""
    event = MagicMock()
    event.content = MagicMock()
    event.content.role = "model"
    event.content.parts = [MagicMock(text=text)]
    return event


async def _fake_run_async_greeting(*args, **kwargs):
    """Async generator yielding a simple greeting event."""
    yield _make_fake_event("Hello! I'm your IT Business Consultant.")


async def _fake_run_async_with_rs(*args, **kwargs):
    """Async generator yielding an event that includes the RS marker."""
    yield _make_fake_event(
        f"I have gathered enough information.\n\n{RS_MARKER}\n{SAMPLE_RS_MARKDOWN}"
    )


@pytest.fixture
def app_with_mocks():
    """
    Import and return the FastAPI app with the ADK runner and session service
    fully mocked. Returns (app, mock_runner, mock_session_service).
    """
    import importlib

    import main as main_module  # noqa — imported after stubs installed

    importlib.reload(main_module)  # re-evaluate module-level globals with stubs

    mock_session = MagicMock()
    mock_session.events = []

    mock_svc = MagicMock()
    mock_svc.get_session = AsyncMock(return_value=mock_session)
    mock_svc.create_session = AsyncMock(return_value=mock_session)

    mock_runner = MagicMock()
    mock_runner.run_async = _fake_run_async_greeting

    main_module.session_service = mock_svc
    main_module.runner = mock_runner

    return main_module.app, mock_runner, mock_svc, mock_session


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(app_with_mocks):
    app, *_ = app_with_mocks
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_reply_and_session_id(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/chat",
            json={"message": "Hello", "session_id": None},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "reply" in body
    assert "session_id" in body
    assert isinstance(body["session_id"], str)
    assert len(body["session_id"]) > 0


@pytest.mark.asyncio
async def test_chat_reply_contains_agent_text(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/chat", json={"message": "Hi there"})

    assert "Hello" in resp.json()["reply"]


@pytest.mark.asyncio
async def test_chat_reuses_session_id(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting
    session_id = "my-fixed-session"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/chat", json={"message": "Follow-up", "session_id": session_id}
        )

    assert resp.json()["session_id"] == session_id


# ---------------------------------------------------------------------------
# POST /chat/stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_sends_session_id_event(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/chat/stream",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )

    assert resp.status_code == 200
    raw = resp.text
    # First SSE event must carry session_id
    lines = [line for line in raw.split("\n") if line.startswith("data: ")]
    first_data = json.loads(lines[0][6:])
    assert "session_id" in first_data


@pytest.mark.asyncio
async def test_chat_stream_ends_with_done(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/chat/stream", json={"message": "Hello"})

    assert "data: [DONE]" in resp.text


@pytest.mark.asyncio
async def test_chat_stream_contains_text_chunk(app_with_mocks):
    app, mock_runner, *_ = app_with_mocks
    mock_runner.run_async = _fake_run_async_greeting

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/chat/stream", json={"message": "Hello"})

    lines = [
        line
        for line in resp.text.split("\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    text_events = [json.loads(line[6:]) for line in lines if "{" in line]
    text_chunks = [e["text"] for e in text_events if "text" in e]
    assert len(text_chunks) > 0
    assert any("Hello" in chunk or "Consultant" in chunk for chunk in text_chunks)


# ---------------------------------------------------------------------------
# POST /document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_returns_not_ready_without_rs(app_with_mocks):
    """Before any RS generation, document endpoint returns ready=False."""
    app, mock_runner, mock_svc, mock_session = app_with_mocks
    mock_session.events = []
    mock_runner.run_async = _fake_run_async_greeting

    session_id = "doc-test-session"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/document", json={"session_id": session_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    assert body["markdown"] is None


@pytest.mark.asyncio
async def test_document_returns_ready_with_rs_marker(app_with_mocks):
    """After the agent produces [GENERATE_RS], document endpoint returns ready=True."""
    app, mock_runner, mock_svc, mock_session = app_with_mocks

    # Simulate session history containing the RS marker
    event = MagicMock()
    event.content = MagicMock()
    event.content.role = "model"
    event.content.parts = [
        MagicMock(text=f"Here is your document.\n\n{RS_MARKER}\n{SAMPLE_RS_MARKDOWN}")
    ]
    mock_session.events = [event]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/document", json={"session_id": "rs-session"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["markdown"] is not None
    assert "Functional Requirements" in body["markdown"]


# ---------------------------------------------------------------------------
# POST /document/pdf
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_pdf_returns_404_without_rs(app_with_mocks):
    """PDF endpoint returns 404 if no RS has been generated."""
    app, mock_runner, mock_svc, mock_session = app_with_mocks
    mock_session.events = []

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/document/pdf", json={"session_id": "empty-session"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_document_pdf_returns_valid_pdf_bytes(app_with_mocks):
    """PDF endpoint returns a valid PDF when the session contains an RS."""
    app, mock_runner, mock_svc, mock_session = app_with_mocks

    event = MagicMock()
    event.content = MagicMock()
    event.content.role = "model"
    event.content.parts = [
        MagicMock(text=f"Document ready.\n\n{RS_MARKER}\n{SAMPLE_RS_MARKDOWN}")
    ]
    mock_session.events = [event]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/document/pdf", json={"session_id": "pdf-session"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


@pytest.mark.asyncio
async def test_document_pdf_has_correct_disposition_header(app_with_mocks):
    """PDF response has Content-Disposition attachment header."""
    app, mock_runner, mock_svc, mock_session = app_with_mocks

    event = MagicMock()
    event.content = MagicMock()
    event.content.role = "model"
    event.content.parts = [MagicMock(text=f"{RS_MARKER}\n{SAMPLE_RS_MARKDOWN}")]
    mock_session.events = [event]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/document/pdf", json={"session_id": "pdf-session-2"})

    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "requirement_specification.pdf" in resp.headers.get(
        "content-disposition", ""
    )


# ---------------------------------------------------------------------------
# End-to-end scripted conversation (Task 6.2 core)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_scripted_conversation(app_with_mocks):
    """
    Simulate a multi-turn scripted conversation:
      1. User describes their project → agent responds with greeting
      2. User answers As-Is questions → agent responds
      3. User answers To-Be questions → agent triggers RS generation
      4. /document confirms the RS is ready
      5. /document/pdf delivers a valid PDF
    """
    app, mock_runner, mock_svc, mock_session = app_with_mocks
    session_id = "scripted-e2e-session"
    collected_events = []
    mock_session.events = collected_events

    turn_responses = [
        "Welcome! Let's start. Can you describe your current process?",
        "Understood. What does success look like for you?",
        "I have enough information.\n\n" + RS_MARKER + "\n" + SAMPLE_RS_MARKDOWN,
    ]
    turn_index = {"i": 0}

    async def fake_run_async(*args, **kwargs):
        text = turn_responses[turn_index["i"]]
        turn_index["i"] += 1
        event = MagicMock()
        event.content = MagicMock()
        event.content.role = "model"
        event.content.parts = [MagicMock(text=text)]
        collected_events.append(event)
        yield event

    mock_runner.run_async = fake_run_async

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Turn 1 — project description
        r1 = await client.post(
            "/chat",
            json={
                "message": "I want to automate sales reports.",
                "session_id": session_id,
            },
        )
        assert r1.status_code == 200
        assert r1.json()["session_id"] == session_id

        # Turn 2 — As-Is
        r2 = await client.post(
            "/chat",
            json={"message": "We do it manually in Excel.", "session_id": session_id},
        )
        assert r2.status_code == 200

        # Turn 3 — To-Be (triggers RS generation)
        r3 = await client.post(
            "/chat",
            json={
                "message": "I want an automated daily email.",
                "session_id": session_id,
            },
        )
        assert r3.status_code == 200
        assert RS_MARKER in r3.json()["reply"]

        # Document should now be ready
        doc_resp = await client.post("/document", json={"session_id": session_id})
        assert doc_resp.status_code == 200
        doc_body = doc_resp.json()
        assert doc_body["ready"] is True
        assert "Functional Requirements" in doc_body["markdown"]

        # PDF should be downloadable
        pdf_resp = await client.post("/document/pdf", json={"session_id": session_id})
        assert pdf_resp.status_code == 200
        assert pdf_resp.content[:5] == b"%PDF-"
