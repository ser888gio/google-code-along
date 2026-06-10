"""Process-wide runtime singletons shared across the API surface.

Access these via attribute lookup (``import runtime`` then ``runtime.runner``)
rather than ``from runtime import runner``. Attribute lookup resolves at call
time, which keeps a single patch point for tests that swap the singletons
with mocks (see tests/test_api_integration.py).
"""

from __future__ import annotations

import time
from typing import Literal

from agent import audio_agent, rs_agent
from config import APP_NAME
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from observability.metrics import record_session_completion, record_session_duration
from session_bridge import SessionBridge

# NOTE: ADK sessions are in-memory only. A backend restart drops all live sessions.
# Firestore persists conversation history and discovery state, so /context/extract
# can reconstruct context after a restart, but any in-flight [FINALIZING] trigger
# will be lost. Migrate to a persistent ADK session store before production.
session_service = InMemorySessionService()

runner = Runner(
    app_name=APP_NAME,
    agent=rs_agent,
    session_service=session_service,
)

# Audio runner for bidi voice streaming (uses native-audio model).
# Intentionally shares session_service with the text runner so SessionBridge
# can inject voice transcripts into the orchestrator's ADK session. The shared
# service is by design — see SessionBridge below.
audio_runner = Runner(
    app_name=APP_NAME,
    agent=audio_agent,
    session_service=session_service,
)

# Bridge: injects voice transcripts into the text orchestrator's ADK session
# so the orchestrator has full context when the user switches back to text.
session_bridge = SessionBridge(
    session_service=session_service,
    app_name=APP_NAME,
    orchestrator_agent_name=rs_agent.name,
)

_session_started_at: dict[str, float] = {}
_session_outcomes_recorded: set[str] = set()


def mark_session_seen(session_id: str) -> None:
    """Remember first-seen time for session duration metrics."""
    _session_started_at.setdefault(session_id, time.monotonic())


def record_session_outcome(
    session_id: str,
    outcome: Literal["finalized", "abandoned"],
) -> None:
    """Record session completion once per backend process."""
    if session_id in _session_outcomes_recorded:
        return
    _session_outcomes_recorded.add(session_id)
    started_at = _session_started_at.pop(session_id, None)
    if started_at is not None:
        record_session_duration(time.monotonic() - started_at, outcome=outcome)
    record_session_completion(outcome=outcome)
