# Frontend Technical Documentation

## Overview

The frontend is a **Next.js 16** single-page application that provides the conversational chat interface for the RS Generator. It connects to the backend over HTTP and WebSocket, renders AI responses in real time, and displays a live Requirement Specification sidebar that updates as the agent extracts field values from the conversation.

---

## Technology Stack

| Technology | Version | Purpose |
|---|---|---|
| Next.js | 16.2.4 | React framework, routing, SSR/standalone output |
| React | 19.2.3 | UI rendering |
| TypeScript | 5.9.3 | Static typing (strict mode) |
| Tailwind CSS | 4.x | Utility-first styling |
| Mermaid.js | 11.14.0 | Client-side BPMN/dataflow diagram rendering |
| react-markdown | 10.1.0 | Markdown rendering for agent responses |
| remark-gfm | 4.0.1 | GitHub-Flavored Markdown plugin |
| Jest | 30.x | Unit and component testing |
| @testing-library/react | 16.x | React component test utilities |
| knip | 6.x | Dead code and unused dependency detection |

**Node.js requirement:** >= 22.0.0
**npm requirement:** >= 10.2.3

---

## Directory Structure

```
frontend/
├── app/
│   ├── admin/
│   │   ├── metrics/page.tsx           # Admin metrics dashboard
│   │   └── sessions/[id]/page.tsx     # Session detail view
│   ├── components/
│   │   ├── RsLiveTemplate.tsx         # Live RS sidebar (primary component)
│   │   ├── AnalysisPanel.tsx          # Final analysis display
│   │   ├── BpmnPanel.tsx              # BPMN diagram panel
│   │   ├── DataflowPanel.tsx          # Dataflow diagram panel
│   │   ├── FileUpload.tsx             # GCS file upload widget
│   │   ├── FirestoreSrsPanel.tsx      # Firestore-backed SRS panel
│   │   ├── MermaidDiagram.tsx         # Mermaid.js renderer wrapper
│   │   └── MessageBubbles.tsx         # Chat message rendering
│   ├── i18n/
│   │   ├── LocaleContext.tsx          # Czech/English context provider
│   │   └── LanguageSwitcher.tsx       # CZ/EN toggle UI
│   ├── generated/
│   │   └── rsSchema.ts                # AUTO-GENERATED — do not edit
│   ├── layout.tsx                     # Root layout (providers, fonts)
│   ├── page.tsx                       # Main page (chat UI entry point)
│   └── providers.tsx                  # React context providers wrapper
├── lib/
│   ├── api.ts                         # HTTP API client, SSE/streaming helpers
│   ├── useWebSocket.ts                # WebSocket connection hook
│   ├── useAudioRecorder.ts            # Microphone capture hook
│   └── useAudioPlayer.ts             # Audio playback hook
├── Dockerfile                         # Multi-stage Node 22 Alpine build
├── next.config.ts                     # API proxy rewrites, standalone output
├── tsconfig.json                      # TypeScript config
├── jest.config.ts                     # Jest configuration
├── jest.setup.ts                      # Jest global setup
└── .env.local.example                 # Environment variable template
```

---

## Environment Variables

Copy `.env.local.example` to `.env.local` before running locally.

| Variable | Example | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8080` | Backend base URL (HTTP) |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8080` | Backend WebSocket URL |
| `NEXT_PUBLIC_ADMIN_API_TOKEN` | `your-token` | Bearer token for admin endpoints |
| `NEXT_SERVER_ACTION_ALLOWED_ORIGINS` | `localhost:3000` | Allowed origins for Server Actions |

In production these are injected as Docker build arguments (see [Deployment](deployment.md)).

---

## Key Components

### `page.tsx` — Main Chat UI

The root page component. It:

- Initializes a session ID (UUID) on first render
- Manages conversation message state
- Renders the chat input, message thread, and `RsLiveTemplate` sidebar side by side
- Dispatches user messages to the backend via WebSocket or SSE streaming
- Handles file upload state and passes GCS URIs to the backend

### `components/RsLiveTemplate.tsx` — Live RS Sidebar

The most complex frontend component. It reads the auto-generated schema from `app/generated/rsSchema.ts` and renders all **6 sections** and **22+ fields** of the Requirement Specification in real time.

**Card types:**

| Card | Description | Visual |
|---|---|---|
| `PlaceholderCard` | Field not yet filled | Dashed border, pulsing shimmer |
| `FilledCard` | Value extracted by AI | White background, "AI" badge |
| `EditableCard` | Direct user input | Blue border, "Direct" badge, input/textarea |

**Behavior:**

- Polls or receives WebSocket events with `discovery_state` from the backend
- Renders a progress indicator per section (e.g., "3 / 5 fields filled")
- `EditableCard` fields post their values directly to the backend `PATCH /session/{id}/direct-fields` endpoint
- Labels and section titles are translated based on the active locale (`LocaleContext`)

### `components/MermaidDiagram.tsx`

Wraps the Mermaid.js library for client-side rendering. Receives a Mermaid syntax string from the backend and renders it as an SVG diagram. Used by `BpmnPanel.tsx` and `DataflowPanel.tsx`.

### `components/MessageBubbles.tsx`

Renders individual chat turns. User messages are right-aligned; agent messages are left-aligned and parsed through `react-markdown` with `remark-gfm` for full Markdown support (tables, code blocks, etc.).

### `components/FileUpload.tsx`

Drag-and-drop file upload widget. Uploads files directly to GCS via a signed URL obtained from the backend, then sends the resulting GCS URI to the agent for multimodal analysis.

### `lib/api.ts`

Central HTTP client. Key exports:

- `sendMessage(sessionId, message, signal)` — POST a message and consume a Server-Sent Events stream
- `getSessionState(sessionId)` — GET current discovery state
- `patchDirectFields(sessionId, fields)` — PATCH direct user inputs
- `downloadPdf(sessionId)` / `downloadDocx(sessionId)` — trigger document export and save file

### `lib/useWebSocket.ts`

React hook that manages a persistent WebSocket connection for the audio mode (Gemini Live API bidirectional streaming). Handles reconnection and message queuing.

### `lib/useAudioRecorder.ts` / `lib/useAudioPlayer.ts`

Hooks that wrap the Web Audio API and MediaRecorder. Used for the voice interaction feature powered by Gemini Live API.

---

## Internationalization (i18n)

The app supports **Czech** and **English** via a library-free implementation.

- Translation files: `app/i18n/cs.json` and `app/i18n/en.json`
- Context: `app/i18n/LocaleContext.tsx` provides the active locale and a `t(key)` helper to all components
- Toggle: `app/i18n/LanguageSwitcher.tsx` renders a CZ / EN button in the navbar
- The admin panel is excluded from i18n (English only)

---

## Auto-Generated Schema

`app/generated/rsSchema.ts` is generated by the backend script and **must never be edited by hand**.

It exports:

```typescript
export const RS_SECTIONS: Section[]
export const RS_FIELDS: Record<string, Field>
```

Each `Field` contains `key`, `label` (in CZ and EN), `section`, `directInput`, `multiline`, and other metadata. `RsLiveTemplate.tsx` imports this to know which fields to render.

To regenerate after changing `backend/field_schema.py`:

```bash
cd backend
.venv/Scripts/python scripts/generate_frontend_schema.py
```

---

## API Routing

`next.config.ts` defines reverse-proxy rewrites so the browser can reach the backend without CORS issues in local development:

```
/api/* → http://localhost:8080/*
/ws/*  → ws://localhost:8080/*
```

In production, the frontend container has `NEXT_PUBLIC_API_URL` set to the backend Cloud Run URL and communicates directly (no proxy needed).

---

## Running Locally

```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in values
npm run dev
```

The dev server starts at `http://localhost:3000` with hot reload enabled.

---

## Building for Production

```bash
npm run build   # outputs a standalone Next.js server bundle
npm start       # runs the production server on port 3000
```

The build uses `--webpack` explicitly (Turbopack is not used).

---

## Testing

```bash
cd frontend
npm test              # run all Jest tests once
npm run test:watch    # watch mode
```

Tests live alongside components or in `__tests__/` directories. They use `@testing-library/react` for rendering and interaction.

Dead-code and unused dependency checks:

```bash
npm run knip
```

---

## Docker Build

```dockerfile
# Multi-stage: deps → builder → runner
FROM node:22-alpine AS runner
# Build args injected at image build time:
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_ADMIN_API_TOKEN
EXPOSE 3000
```

The image uses Next.js standalone output mode, so the final image contains only the minimal production bundle (no `node_modules` copied in full).

---

## Admin Dashboard

Available at `/admin/metrics` and `/admin/sessions/[id]` (protected by the `NEXT_PUBLIC_ADMIN_API_TOKEN` bearer token). Shows:

- Aggregated session metrics (token counts, cost, field fill rates)
- Per-session conversation history and extracted field values
- Safety flags and anomaly indicators

---

## Known Constraints

- `app/generated/rsSchema.ts` is auto-generated — any manual edits are overwritten on the next schema generation run.
- The `dev` and `build` scripts use `--webpack` flag; do not switch to Turbopack without verifying Mermaid.js compatibility.
- Audio mode requires a secure context (HTTPS or localhost) for `MediaRecorder` access.
