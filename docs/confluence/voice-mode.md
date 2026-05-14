# Voice Mode Guide

## Overview

Voice mode lets the user run the same RS discovery conversation through microphone input and assistant audio output. It uses:

- Browser AudioWorklets for raw PCM capture and playback.
- A frontend WebSocket hook for bidirectional binary/text frames.
- A FastAPI WebSocket endpoint.
- Google ADK live streaming through the audio agent.
- Gemini Live audio model.
- A session bridge that injects voice transcripts into the text orchestrator session.

The important product behavior is that voice and text share the same session context. A user can talk for a while, switch back to text, and the text orchestrator should know what was said in voice mode.

---

## Key Files

| Area | File | Purpose |
|---|---|---|
| Frontend WebSocket | `frontend/lib/useWebSocket.ts` | Connects to `/ws/{user_id}/{session_id}`, sends audio, receives audio and transcript events. |
| Frontend recorder | `frontend/lib/useAudioRecorder.ts` | Captures microphone audio and emits 16 kHz Int16 PCM chunks. |
| Frontend player | `frontend/lib/useAudioPlayer.ts` | Plays assistant 24 kHz Int16 PCM chunks. |
| Recorder worklet | `frontend/public/pcm-recorder-processor.js` | Converts microphone samples to raw PCM chunks. |
| Player worklet | `frontend/public/pcm-player-processor.js` | Buffers and plays raw PCM output. |
| Main UI wiring | `frontend/app/page.tsx` | Starts/stops voice mode, renders transcripts, refreshes extraction. |
| Backend route | `backend/main.py` | Defines `@app.websocket("/ws/{user_id}/{session_id}")`. |
| WebSocket pipeline | `backend/audio_websocket.py` | Bridges browser frames to ADK Live and sends model output back. |
| Text session bridge | `backend/session_bridge.py` | Injects voice transcripts into the shared text ADK session. |
| Agent config | `backend/agent/agent.py` | Defines the audio agent and text orchestrator agent. |

---

## Runtime Configuration

Frontend:

```text
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

In deployed environments this should be:

```text
NEXT_PUBLIC_WS_URL=wss://<backend-host>
```

Backend model configuration is controlled by the audio model setting in `backend/config.py`, exposed in code as:

```python
MODEL_AUDIO
```

The backend builds a live `RunConfig` for the audio session in `backend/main.py`.

Voice mode requires a secure browser context:

- `localhost` for local development.
- HTTPS in deployed environments.

Without a secure context, browser microphone APIs are not available.

---

## High-Level Flow

```text
Browser
  |
  | microphone PCM, 16 kHz mono
  v
useAudioRecorder + pcm-recorder-processor.js
  |
  | binary WebSocket frames
  v
useWebSocket
  |
  | WS /ws/{user_id}/{session_id}
  v
FastAPI websocket_audio
  |
  v
audio_websocket.run_audio_websocket
  |
  | LiveRequestQueue
  v
ADK audio_runner.run_live
  |
  v
Gemini Live audio model
  |
  | audio output + transcription events
  v
Backend WebSocket
  |
  | binary PCM + JSON transcript events
  v
Frontend player and transcript UI
```

At the end of each voice turn:

```text
voice user transcript + assistant transcript
  |
  v
SessionBridge.inject_voice_turn(...)
  |
  v
shared ADK InMemorySessionService
  |
  v
text orchestrator can continue with voice context
```

---

## Frontend Audio Capture

Implementation:

```text
frontend/lib/useAudioRecorder.ts
frontend/public/pcm-recorder-processor.js
```

The hook:

1. Calls `navigator.mediaDevices.getUserMedia`.
2. Requests mono audio with echo cancellation, noise suppression, and auto gain control.
3. Creates an `AudioContext` with a 16 kHz sample-rate hint.
4. Loads `/pcm-recorder-processor.js`.
5. Connects microphone source to the AudioWorklet.
6. Receives raw PCM chunks from the worklet.
7. Calls `onAudioData(pcmData)` for each chunk.

Audio format sent to the backend:

| Property | Value |
|---|---|
| Encoding | Raw PCM |
| Sample type | Int16 |
| Channels | Mono |
| Sample rate | 16 kHz |
| Transport | Binary WebSocket frame |

Browser note: the requested `AudioContext` sample rate is a hint. Browsers may still capture internally at 44.1 or 48 kHz, so the worklet is responsible for producing the expected PCM output.

---

## Frontend Audio Playback

Implementation:

```text
frontend/lib/useAudioPlayer.ts
frontend/public/pcm-player-processor.js
```

The hook:

1. Initializes only after a user gesture to satisfy autoplay policies.
2. Creates an `AudioContext` at 24 kHz.
3. Loads `/pcm-player-processor.js`.
4. Sends received PCM chunks to the player worklet.
5. Tracks playback state.
6. Supports draining or stopping the buffer.

Audio format received from the backend:

| Property | Value |
|---|---|
| Encoding | Raw PCM |
| Sample type | Int16 |
| Channels | Mono |
| Sample rate | 24 kHz |
| Transport | Binary WebSocket frame |

---

## Frontend WebSocket Protocol

Implementation:

```text
frontend/lib/useWebSocket.ts
```

Connection URL:

```text
${NEXT_PUBLIC_WS_URL}/ws/{userId}/{sessionId}
```

The hook state is:

```text
disconnected | connecting | connected | error
```

### Client To Server

| Frame | Shape | Meaning |
|---|---|---|
| Binary | `ArrayBuffer` | Raw microphone PCM audio. |
| Text JSON | `{"type":"text","text":"..."}` | Text fallback sent to Gemini Live. |

The backend also supports these JSON text frame types:

| Type | Shape | Meaning |
|---|---|---|
| `audio` | `{"type":"audio","data":"<base64-pcm>"}` | Base64 audio fallback. |
| `end_of_turn` | `{"type":"end_of_turn"}` | Sends an empty realtime audio blob. |

The current frontend hook mainly uses binary audio frames and `type=text`.

### Server To Client

| Frame | Shape | Meaning |
|---|---|---|
| Binary | `ArrayBuffer` | Assistant audio PCM for playback. |
| Text JSON | `{"type":"user_transcript_partial","text":"..."}` | Live caption chunk while user speaks. |
| Text JSON | `{"type":"user_transcript","text":"..."}` | Final recognized user transcript. |
| Text JSON | `{"type":"text","text":"..."}` | Assistant text transcript. |
| Text JSON | `{"type":"turn_complete","finalizing":false}` | Voice turn ended. |
| Text JSON | `{"type":"error","message":"..."}` | Backend or Gemini Live error. |

The frontend should refresh discovery state after `turn_complete`, similar to the text-chat post-turn extraction flow.

---

## Backend WebSocket Entry Point

Route:

```text
WS /ws/{user_id}/{session_id}
```

Defined in:

```text
backend/main.py
```

On connect, the backend:

1. Accepts the WebSocket.
2. Marks the session as seen for session metrics.
3. Builds the audio `RunConfig`.
4. Calls `run_audio_websocket(...)`.

The audio runner and text runner intentionally share the same ADK `InMemorySessionService`.

```text
runner       -> text orchestrator
audio_runner -> audio agent
shared       -> session_service
```

This shared service is what allows voice transcripts to be injected into the same session context used by text chat.

---

## Backend Audio Pipeline

Implementation:

```text
backend/audio_websocket.py
```

The backend creates:

```python
live_request_queue = LiveRequestQueue()
```

Then it runs two async loops concurrently:

```text
_websocket_audio_upstream
_websocket_audio_downstream
```

### Upstream Loop

Browser to Gemini Live:

```text
WebSocket receive
  |
  | binary audio
  v
Blob(mime_type="audio/pcm;rate=16000")
  |
  v
live_request_queue.send_realtime(...)
```

For text JSON fallback:

```text
{"type":"text","text":"..."}
  |
  v
Content(role="user", parts=[Part.from_text(...)])
  |
  v
live_request_queue.send_content(...)
```

When the client disconnects or an upstream error occurs, the queue is closed.

### Downstream Loop

Gemini Live to browser:

```text
audio_runner.run_live(...)
  |
  v
ADK live events
  |
  | inline audio data
  v
websocket.send_bytes(...)
```

The same loop also handles transcription events:

- Input transcription partials.
- Input transcription finals.
- Output transcription finals.
- Final response events.

---

## Turn Completion And Transcript Injection

The backend collects one `VoiceTurnTranscripts` object per voice turn:

```python
user: str
assistant: str
```

During the turn:

- Final user transcription updates `turn.user`.
- Final assistant transcription updates `turn.assistant`.
- Assistant transcript sent to the frontend has the finalization marker removed for display.

When ADK reports a final response:

```text
_complete_voice_turn(...)
```

does this:

1. Detects whether the assistant text contains the finalization marker.
2. Injects user and assistant transcripts into the text ADK session.
3. Sends `{"type":"turn_complete","finalizing": ...}` to the frontend.
4. Starts shared post-turn processing in the background.
5. Resets the turn transcript buffer.

The injection step is:

```text
SessionBridge.inject_voice_turn(...)
```

If injection fails, the backend logs:

```text
event=bridge_injection_failure_total
```

This event is used by a log-based Cloud Monitoring metric.

---

## Shared Post-Turn Processing

Voice and text share the same post-turn function:

```text
backend/main.py::_run_turn_postprocessing
```

For voice mode, it receives:

- `session_id`
- `user_id`
- `user_text`
- `assistant_text`
- `is_finalizing`

It then:

1. Persists the conversation turn to Firestore.
2. If finalizing, marks finalization pending.
3. Builds a transcript from the ADK session or a fallback text transcript.
4. Extracts final discovery fields.
5. Starts the finalizer.

Normal discovery extraction is still triggered by the frontend after a completed turn through:

```text
POST /context/extract
```

This avoids running heavy extraction twice on every voice turn.

---

## Finalization In Voice Mode

The audio agent can emit the same finalization marker as text mode.

Backend behavior:

```text
assistant_text contains [FINALIZING]
  |
  v
is_finalizing = true
  |
  v
send {"type":"turn_complete","finalizing":true}
  |
  v
_run_turn_postprocessing starts finalizer
```

Frontend behavior should mirror text mode:

1. Switch to the Analysis tab.
2. Show finalizing state.
3. Poll `GET /analyses/{session_id}` every few seconds.
4. Render final analysis when status becomes `complete`.

---

## Error Handling

### Frontend

The WebSocket hook reports:

- `connecting`
- `connected`
- `disconnected`
- `error`

It does not currently implement automatic reconnection or message queuing.

The recorder can fail when:

- Browser is not in a secure context.
- User denies microphone permission.
- AudioWorklet module fails to load.
- Browser does not support the required audio APIs.

The player can fail when:

- It is initialized before a valid user gesture.
- The worklet cannot load.
- Audio output is unavailable.

### Backend

Backend error handling sends JSON events where possible:

```json
{"type":"error","message":"A voice API error occurred. Please try again."}
```

or:

```json
{"type":"error","message":"An internal error occurred. Please reconnect."}
```

Gemini Live close code `1000` is treated as normal closure.

---

## Debugging Checklist

### Voice Button Does Nothing

Check:

1. Browser is using `localhost` or HTTPS.
2. Microphone permission was granted.
3. Browser console for `useAudioRecorder` or `useAudioPlayer` errors.
4. `/pcm-recorder-processor.js` and `/pcm-player-processor.js` load successfully.

### WebSocket Does Not Connect

Check:

1. `NEXT_PUBLIC_WS_URL`.
2. Backend is running on the expected host/port.
3. Cloud Run allows WebSocket traffic.
4. Browser network panel shows `101 Switching Protocols`.
5. Backend logs show `[WS] Connected`.

### User Audio Is Not Heard

Check:

1. Binary frames are being sent from the browser.
2. Recorder is producing chunks.
3. Backend upstream loop receives bytes.
4. Audio blob MIME type is `audio/pcm;rate=16000`.
5. Gemini Live API errors in backend logs.

### Assistant Audio Is Not Playing

Check:

1. Backend sends binary frames.
2. `useAudioPlayer.init()` was called from a user gesture.
3. Player worklet loaded.
4. Browser autoplay policy did not block output.
5. PCM format is 24 kHz Int16 mono.

### Text Mode Does Not Remember Voice Mode

Check:

1. Backend logs show `Post-injection verify`.
2. No `event=bridge_injection_failure_total` log.
3. `SessionBridge.inject_voice_turn` received non-empty user and assistant text.
4. Text and audio runners share the same `session_service`.
5. Backend did not restart between the voice turn and text turn.

### Preview Does Not Update After Voice Turn

Check:

1. Frontend received `turn_complete`.
2. Frontend called `POST /context/extract`.
3. Backend extraction did not hit the per-session lock indefinitely.
4. Firestore discovery state was updated.
5. Cost circuit did not block extraction.

---

## Observability For Voice Mode

Important logs:

| Log text | Meaning |
|---|---|
| `[WS] Connected` | Browser connected to voice endpoint. |
| `[WS] Upstream closed` | Browser-to-backend stream ended. |
| `[WS] Downstream closed` | Gemini-to-browser stream ended. |
| `[WS] Gemini Live API error` | Gemini Live returned an API error. |
| `[WS] Turn complete` | A full user/assistant voice turn completed. |
| `Post-injection verify` | Voice transcript was injected and then verified in ADK session. |
| `event=bridge_injection_failure_total` | Voice transcript injection failed. |

Important metric:

```text
logging.googleapis.com/user/bridge_injection_failure_total
```

This should remain at zero. Any nonzero value means text mode may lose voice context for affected sessions.

---

## Current Limitations

- No automatic WebSocket reconnection.
- No outgoing audio queue when the socket is disconnected.
- No dedicated audio latency metrics yet.
- Live ADK session state is in memory; backend restart loses voice/text live context.
- Uploaded audio is not persisted separately; persisted history relies on transcripts.
- Browser sample-rate behavior can vary; the worklets must keep the PCM contract stable.
- Voice transcript quality depends on Gemini Live transcription quality and microphone conditions.

---

## Developer Change Checklist

When changing voice mode:

1. Test on localhost with microphone permission granted.
2. Confirm WebSocket connects and closes cleanly.
3. Speak a short turn and confirm user transcript appears.
4. Confirm assistant audio plays.
5. Confirm assistant transcript appears.
6. Confirm `turn_complete` fires.
7. Confirm Preview refreshes after the voice turn.
8. Switch to text and ask a follow-up that depends on the voice turn.
9. Check backend logs for bridge injection verification.
10. Check no `bridge_injection_failure_total` event was emitted.
