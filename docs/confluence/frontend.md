# Frontend Technical Documentation

## Overview

The frontend is a **Next.js 16** app for the RS Generator. The main route is a client-side conversational workspace with a chat panel and a live Requirement Specification panel. The app also includes admin routes for observability and transcript review.

The frontend talks to the backend through:

- HTTP `fetch` calls for chat streaming, discovery state, uploads, document generation, diagrams, history, feedback, final analysis, and admin data.
- Server-Sent Events (SSE) for streaming text chat responses.
- WebSocket audio streaming for voice mode.

---

## Technology Stack

| Technology | Version | Purpose |
|---|---:|---|
| Next.js | 16.2.4 | React framework, App Router, standalone production output |
| React / React DOM | 19.2.3 | UI rendering |
| TypeScript | 5.9.3 | Static typing with `strict` enabled |
| Tailwind CSS | 4.x | Utility-first styling through PostCSS |
| @skodaflow/web-library | 8.0.1 | Skoda theme provider |
| Mermaid.js | 11.14.0 | Client-side BPMN/dataflow diagram rendering |
| react-markdown | 10.1.0 | Markdown rendering for agent responses |
| remark-gfm | 4.0.1 | GitHub-Flavored Markdown support |
| Jest | 30.x | Unit tests |
| @testing-library/react | 16.x | React component tests |
| knip | 6.x | Dead-code and unused dependency detection |

**Node.js requirement:** `>=22.0.0`
**npm requirement:** `>=10.2.3`

Scripts:

```bash
npm run dev          # next dev --webpack
npm run build        # next build --webpack
npm start            # next start
npm test             # jest
npm run test:watch   # jest --watch
npm run knip         # knip
npm run lint         # eslint
```

---

## Directory Structure

```text
frontend/
|-- app/
|   |-- admin/
|   |   |-- metrics/page.tsx             # Admin observability dashboard
|   |   `-- sessions/
|   |       |-- page.tsx                  # Admin session review list
|   |       |-- MessageBubbles.tsx        # Admin prompt/completion transcript bubbles
|   |       `-- [id]/page.tsx             # Admin session detail view
|   |-- components/
|   |   |-- RsLiveTemplate.tsx            # Live RS preview panel
|   |   |-- AnalysisPanel.tsx             # Final analysis display
|   |   |-- BpmnPanel.tsx                 # BPMN diagram generation panel
|   |   |-- DataflowPanel.tsx             # Data Flow Diagram generation panel
|   |   |-- FileUpload.tsx                # Multipart upload widget
|   |   |-- FirestoreSrsPanel.tsx         # Firestore-backed SRS data panel
|   |   `-- MermaidDiagram.tsx            # Mermaid renderer wrapper
|   |-- generated/
|   |   `-- rsSchema.ts                   # AUTO-GENERATED - do not edit
|   |-- i18n/
|   |   |-- LocaleContext.tsx             # Czech/English locale context
|   |   |-- LanguageSwitcher.tsx          # CZ/EN toggle UI
|   |   |-- cs.json
|   |   `-- en.json
|   |-- globals.css
|   |-- layout.tsx
|   |-- page.tsx                         # Main chat workspace
|   `-- providers.tsx                     # Locale + Skoda theme providers
|-- lib/
|   |-- api.ts                           # HTTP/SSE API client
|   |-- useWebSocket.ts                  # Voice-mode WebSocket hook
|   |-- useAudioRecorder.ts              # AudioWorklet microphone PCM recorder
|   `-- useAudioPlayer.ts                # AudioWorklet PCM player
|-- public/
|   |-- skoda.png
|   |-- pcm-recorder-processor.js
|   `-- pcm-player-processor.js
|-- __tests__/
|   |-- api.test.ts
|   `-- components.test.tsx
|-- Dockerfile
|-- eslint.config.mjs
|-- jest.config.ts
|-- jest.setup.ts
|-- knip.json
|-- next.config.ts
|-- package.json
|-- postcss.config.mjs
`-- tsconfig.json
```

---

## Environment Variables

| Variable | Default / Example | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | code default: `http://localhost:8080` | Backend base URL for browser HTTP/SSE calls. |
| `NEXT_PUBLIC_WS_URL` | code default: `ws://localhost:8080` | Backend WebSocket base URL for audio mode. |
| `NEXT_PUBLIC_ADMIN_API_TOKEN` | empty | Frontend-side bearer token sent to admin endpoints. Backend validates it against `ADMIN_BEARER_TOKEN`. |
| `NEXT_SERVER_ACTION_ALLOWED_ORIGINS` | `localhost:3000` | Allowed origins for Next Server Actions config. |

Current caveat: `.env.local.example` only contains `NEXT_PUBLIC_API_URL=http://localhost:8000` and `NEXT_SERVER_ACTION_ALLOWED_ORIGINS=localhost:3000`, which does not match the code defaults (`8080`) and omits `NEXT_PUBLIC_WS_URL` and `NEXT_PUBLIC_ADMIN_API_TOKEN`.

In Docker builds, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, and `NEXT_PUBLIC_ADMIN_API_TOKEN` are injected as build arguments and baked into the Next.js client bundle.

---

## Main Chat Workspace

`app/page.tsx` is the primary client component. It keeps the active session in React state. Text chat starts with `sessionId = null`; the backend returns the session ID in the first SSE event and the frontend stores it. Voice mode creates a UUID locally when no session exists yet.

Important responsibilities:

- Render a two-panel workspace: chat on the left, RS/document tabs on the right.
- Stream text chat with `streamChat()` against `POST /chat/stream`.
- Handle SSE events for `session_id`, `message_id`, streamed `text`, `active_field`, `field_update`, and `finalizing`.
- Run post-turn extraction with `POST /context/extract` and refresh Firestore SRS data from `GET /firestore/data/{sessionId}`.
- Preserve strict direct-input fields and suggestable direct fields while merging AI-extracted discovery state.
- Track the active workflow field so the header can show what the agent is currently asking for.
- Manage file upload, session history, feedback, finalization state, and voice mode.

Right-side tabs:

| Tab | Component / Behavior |
|---|---|
| Preview | `RsLiveTemplate`, live field completion state and DOCX generation gate |
| BPMN | `BpmnPanel`, calls `POST /bpmn/generate`; requires score >= 90 |
| Data | `DataflowPanel`, calls `POST /dataflow/generate`; requires score >= 70 |
| Database | `FirestoreSrsPanel`, displays Firestore SRS block data |
| Analysis | `AnalysisPanel`, displays finalizer output after `GET /analyses/{sessionId}` returns complete |
| Summary | Download button surface for the RS document |

Finalization flow:

1. Backend emits SSE `{ "event": "finalizing" }` after detecting the finalization marker.
2. Frontend switches to the Analysis tab and shows `FinalizingOverlay`.
3. Frontend polls `GET /analyses/{sessionId}` every 5 seconds until `status === "complete"`.

---

## Live RS Preview

`app/components/RsLiveTemplate.tsx` imports `RS_SECTIONS` from `app/generated/rsSchema.ts` and renders **6 sections / 28 fields**.

Field totals:

| Category | Count |
|---|---:|
| Required fields | 20 |
| Optional fields | 8 |
| Strict direct-input fields | 5 |
| Suggestable direct-input fields | 4 |

Card types:

| Card | Description | Visual |
|---|---|---|
| `PlaceholderCard` | Field is not filled yet | Dashed border, optional shimmer while extraction is running |
| `FilledCard` | Value was extracted by AI | White card with `AI` badge |
| `EditableCard` | Direct user input | Blue border, direct-input badge, input or textarea |

Generation threshold:

- The live preview enables `onGenerateFull` when `completeness >= 80`.
- `onGenerateFull` calls `downloadRsTemplateDocx(sessionId)`, which posts to `POST /document/rs-template/docx`.

Translation caveat:

- Sections are translated through `SECTION_TITLE_KEYS`.
- Field labels are translated through a manual `FIELD_LABEL_KEYS` map.
- Several newer generated fields are currently missing from that map and the JSON translation files, so they fall back to English labels: `target_users`, `report_frequency`, `key_business_questions`, `kpis_and_metrics`, `acceptance_criteria`, and `dimensions_and_cuts`.

---

## Auto-Generated Schema

`app/generated/rsSchema.ts` is generated by `backend/scripts/generate_frontend_schema.py` from `backend/field_schema.py`. Do not edit it by hand.

Current exports:

```typescript
export interface FieldDef
export interface Section
export const RS_SECTIONS: Section[]
export const STRICT_DIRECT_FIELD_KEYS
export const SUGGESTABLE_DIRECT_FIELD_KEYS
export type DirectChatFieldKey
export const DIRECT_CHAT_FIELD_PATTERNS
export const DEFERRED_DIRECT_ANSWER_PATTERNS
```

It does **not** export `RS_FIELDS`, and generated field labels are plain English strings. Locale-specific labels are currently handled separately in `RsLiveTemplate.tsx` and `app/i18n/*.json`.

To regenerate after changing `backend/field_schema.py`:

```bash
cd backend
.venv/Scripts/python scripts/generate_frontend_schema.py
```

---

## API Client

`lib/api.ts` is the central client for HTTP and SSE calls.

Key exports:

| Export | Backend endpoint |
|---|---|
| `streamChat(...)` | `POST /chat/stream` |
| `extractContext(sessionId)` | `POST /context/extract` |
| `getDiscoveryState(sessionId)` | `GET /discovery/{sessionId}` |
| `patchDirectFields(sessionId, fields)` | `PATCH /discovery/{sessionId}/fields` |
| `downloadRsTemplateDocx(sessionId)` | `POST /document/rs-template/docx` |
| `downloadPdf(sessionId)` | `POST /document/docx`; despite the name, downloads a DOCX |
| `generateBpmn(sessionId)` | `POST /bpmn/generate` |
| `generateDataflow(sessionId)` | `POST /dataflow/generate` |
| `uploadFile(file, sessionId, onProgress)` | `POST /upload` multipart form data |
| `getSessionUploads(sessionId)` | `GET /uploads/{sessionId}` |
| `getFirestoreData(sessionId)` | `GET /firestore/data/{sessionId}` |
| `getAnalysis(sessionId)` | `GET /analyses/{sessionId}` |
| `getSessions()` | `GET /sessions` |
| `getHistory(sessionId)` | `GET /history/{sessionId}` |
| `submitFeedback(...)` | `POST /feedback` |
| `updateFeedbackComment(...)` | `PATCH /feedback/{messageId}` |
| `submitSessionFeedback(...)` | `POST /feedback/session` |
| `getAdminMetrics(days)` | `GET /admin/metrics?days=...` |
| `getAdminSessions(filter, limit)` | `GET /admin/sessions` |
| `getAdminSession(sessionId)` | `GET /admin/sessions/{sessionId}` |

---

## File Uploads

`FileUpload.tsx` provides drag-and-drop or file-picker upload. It requires a session ID before upload.

The frontend uploads the first selected file as multipart form data to `POST /upload` through `XMLHttpRequest` so it can report progress. It does not request a signed URL from the backend and does not upload directly from the browser to GCS.

After upload, `page.tsx` refreshes the uploaded-file list with `GET /uploads/{sessionId}` and persists the resulting GCS paths into the `attachments` direct field through `PATCH /discovery/{sessionId}/fields`.

---

## Diagrams

`BpmnPanel.tsx` and `DataflowPanel.tsx` call backend generation endpoints, then render returned Mermaid syntax with `MermaidDiagram.tsx`.

Readiness gates:

- BPMN: backend score must be at least 90.
- Data Flow Diagram: backend score must be at least 70.

`MermaidDiagram.tsx` dynamically imports Mermaid, initializes it with `securityLevel: "strict"`, renders SVG, and writes the SVG into an iframe `srcdoc`.

---

## Voice Mode

Voice mode is built around AudioWorklets and WebSocket frames:

- `useAudioRecorder.ts` uses `navigator.mediaDevices.getUserMedia()` and `/pcm-recorder-processor.js`.
- Recorder output is Int16 mono PCM at 16 kHz, sent as binary WebSocket frames.
- `useAudioPlayer.ts` uses `/pcm-player-processor.js`.
- Player input is Int16 mono PCM at 24 kHz, received as binary WebSocket frames.
- `useWebSocket.ts` connects to `${NEXT_PUBLIC_WS_URL}/ws/{userId}/{sessionId}`.

The WebSocket hook supports connect/disconnect and send/receive operations. It does not currently implement automatic reconnection or message queuing.

Voice mode requires a secure browser context for microphone access: HTTPS or localhost.

---

## Internationalization

The app uses a small custom i18n layer:

- `LocaleContext.tsx` supports `cs` and `en`.
- The default locale is `cs`.
- The selected locale is persisted to `localStorage`.
- `LanguageSwitcher.tsx` exposes the toggle in the main UI.
- Admin pages are English-only.

Known i18n gap: some generated RS fields are not yet present in `FIELD_LABEL_KEYS`, `cs.json`, or `en.json`, so they are not translated in the live preview.

---

## API Routing

`next.config.ts` sets `output: "standalone"` and defines a catch-all rewrite:

```typescript
{
  source: "/:path*",
  destination: `${apiUrl}/:path*`
}
```

This is not a narrow `/api/*` rewrite. The browser-side API client usually calls `NEXT_PUBLIC_API_URL` directly, and the WebSocket client calls `NEXT_PUBLIC_WS_URL` directly. WebSocket traffic is not proxied by the Next rewrite.

---

## Admin Dashboard

Admin routes:

| Route | Purpose |
|---|---|
| `/admin/metrics` | Observability summary for cost, tokens, latency, safety finishes, feedback, model/phase breakdowns, and daily trends |
| `/admin/sessions` | Review list of sessions, with optional `filter=thumbs_down` |
| `/admin/sessions/[id]` | Transcript detail with prompt/completion cards, token/cost details, tool calls, feedback, and Cloud Trace links |

Frontend admin requests send `Authorization: Bearer ${NEXT_PUBLIC_ADMIN_API_TOKEN}` when the token is configured. Backend admin authorization accepts IAP headers or the backend `ADMIN_BEARER_TOKEN`; in non-production environments, an empty backend token allows access.

The admin UI is BigQuery-backed through the backend. It does not currently render extracted RS field values in the session detail page.

---

## Testing

Tests live in `frontend/__tests__/`:

- `api.test.ts`
- `components.test.tsx`

The Jest config uses `ts-jest`, `jsdom`, `jest.setup.ts`, and a CSS module mapper to `__mocks__/styleMock.js`.

---

## Docker Build

The Dockerfile is a three-stage Node 22 Alpine build:

1. `deps`: runs `npm ci`.
2. `builder`: copies source, sets `NEXT_PUBLIC_*` build args as env vars, disables telemetry, runs `npm run build`.
3. `runner`: copies `public`, `.next/standalone`, and `.next/static`, exposes port `3000`, and runs `node server.js`.

The production image uses Next.js standalone output and does not copy the full development source tree into the runtime stage.

---

## Known Constraints And Documentation Drift Risks

- `app/generated/rsSchema.ts` is auto-generated; manual edits are overwritten.
- The schema currently has 28 fields, while some code comments still say "22-field" or "22 RSLiveTemplate fields".
- `downloadPdf()` is a stale function name; it posts to a DOCX endpoint and saves a `.docx`.
- `dev` and `build` use `--webpack`; do not switch to Turbopack without testing Mermaid and the current Next.js setup.
- Voice mode depends on browser microphone permission, AudioWorklet support, and HTTPS/localhost.
- `.env.local.example` should be updated to match the current defaults and required frontend variables.
