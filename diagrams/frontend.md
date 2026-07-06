# Frontend Architecture

The frontend is a **Next.js (App Router)** app. The main route `app/page.tsx` is a two-panel workspace: chat on the left, RS/document/diagram/analysis tabs on the right (`Preview`, `BPMN`, `Data`, `Database`, `Analysis`, `Summary`).

## Structure

- **`app/page.tsx`** — client workspace: streaming chat, session lifecycle, finalization polling, uploads, voice mode, feedback.
- **Hooks** — `useChatSession`, `useMessages`, `useRsState`, `useRsExtraction`, `useVoiceMode` encapsulate session, message, RS-field, extraction, and voice state.
- **Panels** — `RsLiveTemplate` (live RS preview), `BpmnPanel` / `DataflowPanel` (Mermaid diagram requests), `AnalysisPanel` (finalizer output), `FirestoreSrsPanel`, `FileUpload`, `MermaidDiagram`.
- **Cross-cutting** — `i18n/LocaleContext` (Czech/English), `app/generated/rsSchema.ts` (generated from `backend/field_schema.py` — do not edit by hand), `lib/directChatAnswer.ts`.
- **API client** — `lib/api.ts`: typed HTTP, SSE (`streamChat`), and upload helpers.
- **Voice libs** — `lib/useWebSocket.ts`, `lib/useAudioRecorder.ts`, `lib/useAudioPlayer.ts`, plus the `public/pcm-*-processor.js` AudioWorklets for PCM capture/playback.

## Data flow

`page.tsx` drives hooks and panels. Hooks and panels call `lib/api.ts`, which targets the backend Cloud Run service over HTTP and SSE (`POST /chat/stream`, `POST /context/extract`, `/upload`, `/bpmn/generate`, `/dataflow/generate`, `GET /analyses/{id}` polling). Voice mode connects directly over WebSocket `/ws/{user}/{session}`. The generated schema feeds field metadata into the live preview and direct-chat matching.
