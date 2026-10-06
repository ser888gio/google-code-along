# User Flow — Happy Path

The "golden path" a business user walks to turn a conversation into a Requirements
Specification, with no side-tracks. This is the minimal linear view; see
[user-flow.md](./user-flow.md) for the full set of decisions and branches.

## Steps

1. **Open app.** The user opens the workspace URL.
2. **Sign in with Microsoft Entra ID.** The user authenticates via Microsoft Entra ID
   (OAuth2 / OIDC); once authenticated, the session is tied to the signed-in user.
4. **See welcome + empty RS (0%).** Left pane: a welcome bubble and a text box. Right
   pane: the live RS document at **0% completeness** with empty field cards.
5. **Type answer, press Send.** The message posts to `POST /chat/stream` (SSE).
6. **Assistant streams reply; RS fills live.** Tokens stream back; SSE `field_update`
   events progressively fill the right-hand RS panel as fields are extracted.
7. **Keep chatting** — the user answers the assistant's questions turn after turn until
   completeness climbs (back-edge in the diagram).
8. **≥ 80% "ready to generate."** The completeness bar turns green; the Summary-tab
   download button unlocks.
9. **Assistant offers to finalize (≥ 90%) → user says "generate."** The orchestrator
   proposes finalization and the user accepts.
10. **Finalizing overlay + poll every 5 s.** The UI switches to the Analysis tab and polls
   `GET /analyses/{session_id}` every 5 seconds.
11. **Analysis ready.** `AnalysisPanel` renders the technology recommendation, suggested
   team, priority tier, and risks.
12. **Download RS .docx** (`POST /document/rs-template/docx`).
