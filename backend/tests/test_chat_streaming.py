import asyncio
import json
from types import SimpleNamespace
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


def test_generic_streaming_error_skips_postprocessing():
    async def failing_agent_events(*, user_id, user_content, session_id, state):
        state.error_aborted = True
        yield chat_streaming._sse_event({"error": "boom"})

    postprocess = AsyncMock()

    async def collect() -> list[str]:
        return [
            event
            async for event in chat_streaming.chat_stream_event_generator(
                session_id="sess1",
                user_id="user1",
                message="ok",
                workflow_turn={"workflow": {"phase": "discovery", "active_field": None}},
                user_content=None,
            )
        ]

    with (
        patch.object(chat_streaming, "_agent_stream_events", failing_agent_events),
        patch.object(chat_streaming, "run_turn_postprocessing", postprocess),
    ):
        events = asyncio.run(collect())

    assert events[-1] == "data: [DONE]\n\n"
    postprocess.assert_not_called()


def test_hidden_choices_block_that_fails_to_parse_falls_back_to_full_text():
    state = chat_streaming.StreamReplyState()
    state.hiding_choices = True
    events = chat_streaming._choices_events("Vyberte: <choices>[broken", state, session_id="sess1")

    assert len(events) == 1
    assert json.loads(events[0][len("data: ") :])["text_replace"] == "Vyberte: <choices>[broken"


# ---------------------------------------------------------------------------
# Token streaming
# ---------------------------------------------------------------------------


def _visible(chunks: list[str]) -> str:
    state = chat_streaming.StreamReplyState()
    shown = [chat_streaming._take_visible_text(state, chunk) for chunk in chunks]
    shown.append(chat_streaming._take_visible_text(state, "", flush=True))
    return "".join(shown)


def test_marker_split_across_chunks_is_never_shown():
    assert _visible(["Hotovo. [FINAL", "IZING] Analýza bude brzy."]) == "Hotovo.  Analýza bude brzy."


def test_choices_block_is_held_back_from_the_stream():
    assert _visible(["Vyberte prosím: ", "<cho", 'ices>["A", "B"]</choices>']) == "Vyberte prosím: "


def test_text_that_only_looks_like_a_tag_start_is_released():
    state = chat_streaming.StreamReplyState()
    assert chat_streaming._take_visible_text(state, "Cena je [") == "Cena je "
    assert chat_streaming._take_visible_text(state, "500 Kč].") == "[500 Kč]."


def _event(text: str, *, partial: bool | None) -> SimpleNamespace:
    return SimpleNamespace(partial=partial, content=SimpleNamespace(parts=[SimpleNamespace(text=text, thought=None)]))


def test_partial_events_stream_and_the_aggregated_copy_is_skipped():
    calls: list[dict] = []

    async def run_async(**kwargs):
        calls.append(kwargs)
        for event in (
            _event("Dobrý ", partial=True),
            _event("den.", partial=True),
            _event("Dobrý den.", partial=False),
        ):
            yield event

    async def collect(state) -> list[str]:
        return [
            event
            async for event in chat_streaming._agent_stream_events(
                user_id="user1", user_content=None, session_id="sess1", state=state
            )
        ]

    state = chat_streaming.StreamReplyState()
    with patch.object(chat_streaming.runtime, "runner", SimpleNamespace(run_async=run_async)):
        events = asyncio.run(collect(state))

    assert [json.loads(event[len("data: ") :])["text"] for event in events] == ["Dobrý ", "den."]
    assert "".join(state.reply_parts) == "Dobrý den."
    assert calls[0]["run_config"] is chat_streaming._TEXT_RUN_CONFIG
