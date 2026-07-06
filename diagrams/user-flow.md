# User Flow — Interaction & Decisions

The full behavioral flow of a business user working with the RS Generator: the
per-turn discovery loop, the side actions available at any time, the completeness
gates, the wrap-up/finalize decision, and the finalization polling with its outcomes.
For the stripped-down linear view see [user-flow-happy-path.md](./user-flow-happy-path.md).

## Entry

- **Open workspace.** The user opens the app URL.
- **Redirect to Microsoft Entra ID.** The user is sent through a Microsoft Entra ID
  **OAuth2 / OIDC** sign-in. On failure the user retries; on success the flow continues.
- **Session minted for the signed-in user.** Once **authenticated**, a `session_id` is
  established and tied to the Entra ID user identity.
- **Landing.** Welcome bubble, **0%** completeness, empty field cards (28 fields / 6
  sections), tabs Preview / Database / Summary.

## Discovery loop (per turn)

1. **User sends message** → `POST /chat/stream` (SSE).
2. **Answer classified?** The backend classifies the reply:
   - **answered** → field filled (`ANSWERED`),
   - **clarification** → assistant re-asks,
   - **deferred / skip** → field parked (`DEFERRED`), resurfaced at wrap-up.
3. **Backend advances the FSM** (`DISCOVERY → WRAP_UP → READY_TO_FINALIZE → FINALIZING →
   COMPLETE`) and **picks the next missing field**.
4. **Live `field_update` + choices buttons** stream to the UI; the user can click a
   quick-reply choice or type freely → next turn.

After each turn, `POST /context/extract` recomputes the **completeness %**, which feeds
the completeness gauge and the gates below.

## Side actions (available during the loop)

Upload a file (modal, `POST /upload`) · Toggle **Voice** mode (WebSocket mic +
transcripts, same finalize logic) · Edit a field or Accept/Dismiss an AI suggestion
(`PATCH /discovery/...`) · Thumbs feedback on a message · open the **History** sidebar to
resume a past session (`GET /sessions` → `GET /history/{id}`) · **CZ/EN** language switch.

## Completeness gates

- **≥ 70%** → Data-Flow diagram (Mermaid) unlocks.
- **≥ 80%** → Download RS `.docx` (`POST /document/rs-template/docx`) unlocks.
- **≥ 90%** → BPMN unlocks and the assistant offers to finalize (auto-finalize path).

## Wrap-up & finalize

- **All fields exhausted?** When no missing fields remain the flow reaches wrap-up.
- **Finalize now?**
  - **No** → a deferred field is reopened and discovery resumes.
  - **Yes** → the orchestrator emits the **`[FINALIZING]`** marker → SSE `finalizing`
    event → UI jumps to the Analysis tab + overlay.
- **Poll `GET /analyses/{id}` every 5 s**, then branch on **status?**:
  - **complete** → `AnalysisPanel` (recommendation / team / priority / risks) — done.
  - **pending** → keep polling.
  - **error** → cost-circuit or pipeline failure notice.

## Session end

**End chat → rate 1–5 → input locked** (`POST /feedback/session`). Rating the
conversation closes the session and disables further input.
