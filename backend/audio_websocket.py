from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.genai.errors import APIError as GenaiAPIError
from google.genai.types import Blob, Content, Part


@dataclass(frozen=True)
class AudioWebsocketDeps:
    app_name: str
    finalizing_marker: str
    session_service: Any
    session_bridge: Any
    audio_runner: Any
    run_turn_postprocessing: Callable[..., Any]
    load_voice_priming: Callable[[str], str | None]
    logger: Any


@dataclass
class VoiceTurnTranscripts:
    user: str = ""
    assistant: str = ""

    def reset(self) -> None:
        self.user = ""
        self.assistant = ""


def _pcm_blob(audio_bytes: bytes) -> Blob:
    return Blob(mime_type="audio/pcm;rate=16000", data=audio_bytes)


def _text_content(text: str) -> Content:
    return Content(role="user", parts=[Part.from_text(text=text)])


async def _send_ws_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


async def _ensure_audio_session(deps: AudioWebsocketDeps, user_id: str, session_id: str):
    session = await deps.session_service.get_session(
        app_name=deps.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        session = await deps.session_service.create_session(
            app_name=deps.app_name,
            user_id=user_id,
            session_id=session_id,
        )
    await _prime_audio_session(deps, session, session_id)
    return session


_PRIMING_MARKER = "[VOICE_PRIMING]"


def _latest_priming_text(session) -> str | None:
    """Return the text of the most recent priming event already in history."""
    for event in reversed(session.events or []):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text and text.startswith(_PRIMING_MARKER):
                return text
    return None


async def _prime_audio_session(deps: AudioWebsocketDeps, session, session_id: str) -> None:
    """Seed the audio session history with the hidden workflow-context block.

    Appended as a synthetic user event (not pushed through the live queue) so the
    voice agent sees fields already answered in text mode on its next real turn,
    without being prompted to respond on connect.

    Idempotent across reconnects: each priming event carries a marker prefix, and
    we skip appending when the latest priming block in history is unchanged — so
    repeated text/voice toggles don't accumulate duplicate hidden blocks.
    """
    try:
        priming = await asyncio.get_running_loop().run_in_executor(None, deps.load_voice_priming, session_id)
    except Exception as exc:
        deps.logger.error(f"[WS] Voice priming load failed: session={session_id} {exc}")
        return
    if not priming or not priming.strip():
        return
    tagged = f"{_PRIMING_MARKER}\n{priming}"
    if _latest_priming_text(session) == tagged:
        deps.logger.debug(f"[WS] Voice priming unchanged, skipping append: session={session_id}")
        return
    event = Event(author="user", content=_text_content(tagged))
    await deps.session_service.append_event(session, event)
    deps.logger.info(f"[WS] Voice session primed with workflow context: session={session_id}")


def _send_upstream_text_message(msg: dict, live_request_queue: LiveRequestQueue) -> None:
    msg_type = msg.get("type", "text")
    if msg_type == "audio":
        live_request_queue.send_realtime(_pcm_blob(base64.b64decode(msg["data"])))
    elif msg_type == "text":
        text = msg.get("text", "")
        if text.strip():
            live_request_queue.send_content(_text_content(text))
    elif msg_type == "end_of_turn":
        live_request_queue.send_realtime(_pcm_blob(b""))


async def _handle_audio_upstream_frame(
    websocket: WebSocket,
    live_request_queue: LiveRequestQueue,
    deps: AudioWebsocketDeps,
) -> bool:
    data = await websocket.receive()
    if data.get("type") == "websocket.disconnect":
        return False
    if data.get("bytes"):
        live_request_queue.send_realtime(_pcm_blob(data["bytes"]))
    elif data.get("text"):
        try:
            _send_upstream_text_message(json.loads(data["text"]), live_request_queue)
        except json.JSONDecodeError as exc:
            deps.logger.warning(f"[WS] Invalid JSON from client: {exc}")
    return True


async def _websocket_audio_upstream(
    websocket: WebSocket,
    live_request_queue: LiveRequestQueue,
    deps: AudioWebsocketDeps,
    user_id: str,
    session_id: str,
) -> None:
    try:
        while await _handle_audio_upstream_frame(websocket, live_request_queue, deps):
            pass
    except WebSocketDisconnect:
        deps.logger.debug(f"[WS] Upstream client disconnected: user={user_id} session={session_id}")
    except Exception as exc:
        deps.logger.error(f"[WS] Upstream error: {exc}", exc_info=True)
    finally:
        live_request_queue.close()
        deps.logger.debug(f"[WS] Upstream closed: user={user_id} session={session_id}")


async def _send_audio_content_parts(websocket: WebSocket, event, deps: AudioWebsocketDeps) -> None:
    if not event.content or not event.content.parts:
        return
    for part in event.content.parts:
        inline_data = part.inline_data
        if inline_data and inline_data.mime_type and "audio" in inline_data.mime_type and inline_data.data:
            await websocket.send_bytes(inline_data.data)
        elif part.text:
            deps.logger.debug(f"[WS] Text content event (role={getattr(event.content, 'role', '?')}): {part.text[:80]}")


async def _send_user_transcription(
    websocket: WebSocket,
    event,
    turn: VoiceTurnTranscripts,
    deps: AudioWebsocketDeps,
) -> None:
    if not event.input_transcription or not event.input_transcription.text:
        return
    if event.partial:
        # Delta chunk — stream as live caption while the user speaks.
        chunk = event.input_transcription.text
        if chunk and chunk.strip():
            await _send_ws_json(websocket, {"type": "user_transcript_partial", "text": chunk})
    else:
        turn.user = event.input_transcription.text
        clean = turn.user.strip()
        if clean:
            await _send_ws_json(websocket, {"type": "user_transcript", "text": clean})
        deps.logger.debug(f"[WS] User transcription final ({len(clean)} chars): {clean[:100]}")


async def _send_assistant_transcription(
    websocket: WebSocket,
    event,
    turn: VoiceTurnTranscripts,
    deps: AudioWebsocketDeps,
) -> None:
    if not event.output_transcription or not event.output_transcription.text or event.partial:
        return
    turn.assistant = event.output_transcription.text
    clean = turn.assistant.replace(deps.finalizing_marker, "").strip()
    if clean:
        await _send_ws_json(websocket, {"type": "text", "text": clean})
    deps.logger.debug(f"[WS] Assistant transcription final ({len(turn.assistant)} chars): {turn.assistant[:100]}")


async def _verify_voice_session_injection(deps: AudioWebsocketDeps, user_id: str, session_id: str) -> None:
    verify = await deps.session_service.get_session(
        app_name=deps.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    if not verify:
        deps.logger.warning(f"[WS] Post-injection: session NOT FOUND in storage! session={session_id}")
        return
    content_events = [
        event
        for event in (verify.events or [])
        if event.content and event.content.parts and any(part.text for part in event.content.parts if part.text)
    ]
    deps.logger.info(
        f"[WS] Post-injection verify: session={session_id} "
        f"total_events={len(verify.events or [])} "
        f"content_text_events={len(content_events)}"
    )


async def _inject_voice_turn(
    deps: AudioWebsocketDeps,
    user_id: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    try:
        await deps.session_bridge.inject_voice_turn(
            user_id=user_id,
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
        )
        await _verify_voice_session_injection(deps, user_id, session_id)
    except Exception as exc:
        deps.logger.error(
            f"[WS] SessionBridge injection failed: event=bridge_injection_failure_total session_id={session_id} {exc}"
        )


async def _complete_voice_turn(
    websocket: WebSocket,
    deps: AudioWebsocketDeps,
    user_id: str,
    session_id: str,
    turn: VoiceTurnTranscripts,
) -> None:
    user_text = turn.user.strip()
    assistant_text = turn.assistant.strip()
    deps.logger.info(
        f"[WS] Turn complete: session={session_id} user_chars={len(user_text)} assistant_chars={len(assistant_text)}"
    )
    is_finalizing = deps.finalizing_marker in assistant_text
    await _inject_voice_turn(deps, user_id, session_id, user_text, assistant_text)
    await _send_ws_json(websocket, {"type": "turn_complete", "finalizing": is_finalizing})
    asyncio.create_task(
        deps.run_turn_postprocessing(
            session_id=session_id,
            user_id=user_id,
            user_text=user_text,
            assistant_text=assistant_text,
            is_finalizing=is_finalizing,
        )
    )
    turn.reset()


async def _send_voice_error(websocket: WebSocket, deps: AudioWebsocketDeps, message: str) -> None:
    try:
        await _send_ws_json(websocket, {"type": "error", "message": message})
    except Exception as exc:
        deps.logger.debug(f"[WS] Failed to deliver voice error to client (socket likely closed): {exc}")


async def _websocket_audio_downstream(
    websocket: WebSocket,
    *,
    session,
    live_request_queue: LiveRequestQueue,
    run_config: RunConfig,
    deps: AudioWebsocketDeps,
    user_id: str,
    session_id: str,
) -> None:
    turn = VoiceTurnTranscripts()
    try:
        async for event in deps.audio_runner.run_live(
            session=session,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            await _send_audio_content_parts(websocket, event, deps)
            await _send_user_transcription(websocket, event, turn, deps)
            await _send_assistant_transcription(websocket, event, turn, deps)
            if event.is_final_response():
                await _complete_voice_turn(websocket, deps, user_id, session_id, turn)
    except WebSocketDisconnect:
        deps.logger.debug("[WS] Client disconnected during downstream")
    except GenaiAPIError as exc:
        if "1000" in str(exc):
            deps.logger.info(f"[WS] Gemini Live session closed normally: session={session_id}")
        else:
            deps.logger.error(f"[WS] Gemini Live API error: {exc}", exc_info=True)
            await _send_voice_error(websocket, deps, "A voice API error occurred. Please try again.")
    except Exception as exc:
        deps.logger.error(f"[WS] Downstream error: {exc}", exc_info=True)
        await _send_voice_error(websocket, deps, "An internal error occurred. Please reconnect.")
    finally:
        deps.logger.debug(f"[WS] Downstream closed: user={user_id} session={session_id}")


async def run_audio_websocket(
    websocket: WebSocket,
    *,
    user_id: str,
    session_id: str,
    run_config: RunConfig,
    deps: AudioWebsocketDeps,
) -> None:
    session = await _ensure_audio_session(deps, user_id, session_id)
    live_request_queue = LiveRequestQueue()
    await asyncio.gather(
        _websocket_audio_upstream(websocket, live_request_queue, deps, user_id, session_id),
        _websocket_audio_downstream(
            websocket,
            session=session,
            live_request_queue=live_request_queue,
            run_config=run_config,
            deps=deps,
            user_id=user_id,
            session_id=session_id,
        ),
    )
