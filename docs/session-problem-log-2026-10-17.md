# Session Problem Log — 17 October 2026

The 17 October 2026 session hit 20 problems. 11 are fixed and deployed (develop `7756d2d`). The biggest open one is reply speed: the first word of a chat reply still takes about 9.8 s on average.

## Problems

| # | Area | What went wrong | Impact | Fix | Status |
|---|---|---|---|---|---|



| 7 | Wrap-up | The finalize decision matched 8 exact words. "Ano, prosím", "finální vygenerování" and similar replies fell through, a deferred field was reopened, and the chat looped. | Old-backend sessions hit the turn limit (35 and 30 turns). Resolution rate was near 0. | Word-stem matching and fixed choice buttons, then a model classifier with the keywords as fallback. | Fixed |
| 8 | Workflow | No early exit: wrap-up only came after every field was resolved, about 33 turns. The simulated user's roughly 10 "let's finish" requests were ignored. | Long interviews; turn-limit endings. | New `FINISH_REQUESTED` transition: defer all open fields and go to wrap-up. | Fixed |
| 9 | Classifier | Shortcuts filed "Můžeme už skončit?" as a clarification question and anything containing "později" as a deferral, before the model saw the message. | Finish requests were invisible. | Those shortcuts removed. Adds about 1 s on those turns. | Fixed |
| 10 | Workflow | `finalizing` and `complete` were never reached. The real outcome lived only in `finalization_status`, so there were two sources of truth. There was no failed state and no retry. | The phase could not measure completion; a failed analysis stranded the session. | Full lifecycle with a new `failed` phase and retry. Phase and status are saved in the same write. | Fixed |
| 11 | Workflow | Text-chat finalization depended on the model printing `[FINALIZING]`. | Missed or premature finalization. | The backend starts finalization when the workflow reaches `ready_to_finalize`. Voice keeps the marker, because voice turns do not advance the workflow. | Fixed |
| 12 | Workflow | Found during the fix: once the later phases became reachable, picking the next field and voice priming would have crashed. A stale chat-turn write could also undo `finalizing`. | Crashes and lost state. | Guards on the phase checks, no workflow write-back during finalization, and no second finalizer. | Fixed |

| 14 | Speed | The chat model ran without streaming, so ADK returned each reply in one piece and the first word arrived only when the reply was complete. | 16–24 s before anything appeared. | Token streaming, with the hidden `[FINALIZING]` marker and `<choices>` block held back while streaming. | Verify |
| 15 | Speed | The Pro model ran at the default high thinking level: about 75% of turn time, with one reply taking 70 s. | Slow replies. | Thinking level set to `low`. `MODEL_ORCHESTRATOR` can now be changed by environment variable to try a faster model. | Partly fixed |
| 16 | Speed | A field extraction ran before every reply (about 2.7 s on average, rising to 3.9 s, against a 4 s timeout). | About 2.7 s added per turn; live field updates would start dropping. | Removed. The frontend's post-turn extraction fills the field panel. | Fixed |



## Open follow-ups

- [ ] Confirm streaming is live: per turn, the first word should arrive clearly before the full reply (#14).
- [ ] If the first word still takes about 10 s, try a faster model with the `MODEL_ORCHESTRATOR` env var on the Cloud Run service, then compare with a forced simulation run (#15).
- [ ] Check that a manually set `MODEL_ORCHESTRATOR` survives the next CI deploy.
- [ ] Grant the CI service account `roles/cloudscheduler.admin`, or document the manual trigger setup (#1).
- [ ] Fix the `/feedback` 404 for votes on messages that are not saved yet (#13).
- [ ] Add backend tests to CI, with the placeholder Firestore settings (#18).
- [ ] Fix the 2 existing ESLint errors (#19).
- [ ] Decide whether `sim-5268f06b` stays in the study: its outcome is valid, but its speed numbers predate the speed fixes.
- [ ] Not yet seen in production: voice finalization, and the failed-analysis-then-retry path.
- [ ] Known limits: the non-streaming `/chat` endpoint never finalizes, and a `complete` session cannot be regenerated.
- [ ] Use separate git worktrees whenever more than one Claude session works on the repo.
- [ ] In the write-up, keep the method caveat: ratings and sentiment come from LLM personas, not people.
