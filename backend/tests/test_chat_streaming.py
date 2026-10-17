import asyncio
from unittest.mock import AsyncMock, patch

import chat_streaming


def _run_stream(phase: str, reply: str):
    async def fake_agent_events(*, user_id, user_content, session_id, state):
        if event := chat_streaming._record_agent_text_chunk(reply, state):
            yield event

    postprocess = AsyncMock()

    async def collect() -> list[str]:
        return [
            event
            async for event in chat_streaming.chat_stream_event_generator(
                session_id="sess1",
                user_id="user1",
                message="ok",
                workflow_turn={"workflow": {"phase": phase, "active_field": None}},
                user_content=None,
            )
        ]

    with (
        patch.object(chat_streaming, "_agent_stream_events", fake_agent_events),
        patch.object(chat_streaming, "run_turn_postprocessing", postprocess),
    ):
        events = asyncio.run(collect())
    return events, postprocess


def test_ready_to_finalize_phase_starts_finalization_without_a_marker():
    events, postprocess = _run_stream("ready_to_finalize", "Shrnutí: vše je zaznamenáno.")

    assert any('"event": "finalizing"' in event for event in events)
    assert postprocess.call_args.kwargs["is_finalizing"] is True


def test_model_marker_alone_does_not_finalize_text_chat():
    events, postprocess = _run_stream("discovery", "Skoro hotovo. [FINALIZING]")

    assert not any('"event": "finalizing"' in event for event in events)
    assert not any("[FINALIZING]" in event for event in events)
    assert postprocess.call_args.kwargs["is_finalizing"] is False
