import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent.finalizer_agent import _persist_finalizer_result, mark_finalizer_failed


def test_successful_finalization_moves_phase_to_complete():
    upsert = MagicMock()
    with (
        patch("agent.finalizer_agent.save_final_analysis", AsyncMock()),
        patch("agent.finalizer_agent.get_workflow_state", return_value={"phase": "finalizing"}),
        patch("agent.finalizer_agent.upsert_final_analysis", upsert),
    ):
        asyncio.run(_persist_finalizer_result("sess1", {"score": 1}))

    session_id, analysis, workflow_state = upsert.call_args.args
    assert (session_id, analysis) == ("sess1", {"score": 1})
    assert workflow_state["phase"] == "complete"


def test_failed_finalization_moves_phase_to_failed():
    set_error = MagicMock()
    with (
        patch("agent.finalizer_agent.get_workflow_state", return_value={"phase": "finalizing"}),
        patch("agent.finalizer_agent.set_finalization_error", set_error),
    ):
        asyncio.run(mark_finalizer_failed("sess1"))

    session_id, workflow_state = set_error.call_args.args
    assert session_id == "sess1"
    assert workflow_state["phase"] == "failed"


def test_status_is_still_written_when_phase_cannot_advance():
    set_error = MagicMock()
    with (
        patch("agent.finalizer_agent.get_workflow_state", return_value={"phase": "discovery"}),
        patch("agent.finalizer_agent.set_finalization_error", set_error),
    ):
        asyncio.run(mark_finalizer_failed("sess1"))

    assert set_error.call_args.args == ("sess1", None)
