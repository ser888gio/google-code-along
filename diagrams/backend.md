# Backend Architecture

The backend is a **FastAPI** service (`backend/main.py`) that wires CORS, OpenTelemetry, and six routers, and hosts the **Google ADK** runtime plus direct Gemini helper pipelines.

## Layers

- **`main.py`** — app entry: CORS middleware, `setup_telemetry(app)`, `/health`, and `include_router` for all API domains.
- **API Routers (`backend/api/`)** — `chat`, `discovery`, `diagrams`, `documents`, `sessions`, `feedback` (one file per domain).
- **Turn Engine** — `chat_turn.py` (classify → advance FSM → persist → maybe finalize), `chat_streaming.py`, `answer_classifier.py`, `answer_quality.py`, and the `workflow_state.py` FSM (`DISCOVERY → WRAP_UP → READY_TO_FINALIZE → FINALIZING → COMPLETE`).
- **ADK Agents + Gemini pipelines** — orchestrator `rs_agent` (Gemini 3.1 Pro) with research tools; audio agent (Gemini 3.1 Flash Live); `discovery_agent` (Flash-Lite) for per-turn field extraction; `finalizer_agent` (Pro) triggered by `[FINALIZING]`; `research_agent` for GCS past-analysis/knowledge-base tools (`search_vertex_ai` is a stub).
- **Voice path** — `audio_websocket.py` streams PCM to the audio agent; `session_bridge.py` injects voice transcripts into the text ADK session.
- **Generation & Diagrams** — `generation/` (srs_compiler, compiler, pdf_export, word_export); `bpmn/` and `dataflow/` emit Mermaid (readiness ≥90 / ≥70).
- **Persistence & Privacy** — `firestore/writer.py`, `gcs/connector.py`, `privacy/redactor.py` (PII redaction before persistence).
- **`field_schema.py`** — canonical 28-field / 6-section schema; codegen source for the frontend schema and extraction/finalizer prompts.

## Key flows

Chat: router → turn engine → orchestrator (streams SSE) → discovery extraction → finalizer on `[FINALIZING]`. Persistence goes through the redactor into Firestore; artifacts and knowledge base live in GCS.
