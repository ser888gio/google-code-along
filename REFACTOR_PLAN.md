# Refactor Plan

Branch: `refactor/maintainability`. Goal: improve maintainability without changing behaviour.

## Baseline

Tests are green as of `7e2beb7`: backend 117/117 (`pytest tests`), frontend 45/45 (`jest`).

| Metric | Backend (Python) | Frontend (TS/TSX, excl. generated) |
|---|---|---|
| Lines of code | 7,595 SLOC (10,220 LOC) | 5,408 non-blank lines |
| Functions analysed | 350 | 337 |
| Average cyclomatic complexity | 3.52 | 2.51 |
| Max cyclomatic complexity | 24 (`compose_rs_field_view`) | 29 (`FieldCard`) |
| Functions with complexity > 10 | 12 | 8 |
| Duplication (jscpd, all code) | 1.78 % of lines; 6 of the 7 clones are BpmnPanel ↔ DataflowPanel | |
| ESLint | — | 6 errors, 9 warnings |

Tools used: radon and vulture (backend), ESLint complexity/length/depth/params rules, knip (clean), jscpd, plus a manual review.
Not analysed: `backend/observability/simulation/` and `backend/tests/test_simulation.py`. They are untracked, appeared during this session and look like in-progress work.

## Ordered plan

Risk: **L** = mechanical, covered by tests or verified unused · **M** = touches logic, tests exist or will be added first · **H** = behaviour or interface surface; needs your decision.

### Tier 1: dead code (low risk, high value)

Before listing anything here I checked for imports, string references, config/YAML/Dockerfile references, tests and FastAPI route registration.

| # | File:line | Issue | Proposed fix | Risk |
|---|---|---|---|---|
| 1 | `backend/agent/prompt.py` (whole file) | `SYSTEM_PROMPT` is never imported. It was superseded by `prompts/agent.py::ORCHESTRATOR_SYSTEM_PROMPT`. Docs still point here. | Delete the file. Update `context.md:57`, `agents.md:99` and `docs/confluence/developer-onboarding.md:224` to point at `prompts/agent.py`. | L |
| 2 | `backend/firestore/writer.py:418` | `_empty_rs_view()` has no callers. | Delete. | L |
| 3 | `backend/firestore/writer.py:785` | `_merge_direct_fields()` has no callers. It is a leftover from the old direct-fields store. | Delete. | L |
| 4 | `backend/config.py:19-20` | `GCS_PREFIX_ANALYSES` and `GCS_PREFIX_KNOWLEDGE_BASE` are unused, while the literals `"analyses/"` and `"knowledge_base/…"` are hardcoded in `agent/finalizer_agent.py:380` and `agent/research_agent.py:77,154-156`. | Use the constants at those sites. The resulting strings are identical. | L |
| 5 | `backend/agent/discovery_agent.py:186` | The TODO refers to `context/extractor.py` and the "22-field schema". That module no longer exists and the schema has 28 fields. | Delete the stale TODO. | L |
| 6 | `backend/api/discovery.py:71` | `_response_from_state` is a one-line pass-through to `compose_rs_field_view`. | Inline it at its call sites. | L |
| 7 | `frontend/app/hooks/useChatSession.ts:115,120` | The `chatMode` and `welcomeText` parameters are unused (lint warnings). | Drop the parameters and update the callers in `page.tsx`. | L |
| 8 | `frontend/app/generated/rsSchema.ts:509-532` | `OPTIONAL_FIELD_KEYS`, `STRICT_DIRECT_FIELD_KEYS` and `SUGGESTABLE_DIRECT_FIELD_KEYS` are emitted but unused, and there is a stale `eslint-disable` at line 4. | Stop emitting them in `backend/scripts/generate_frontend_schema.py` and regenerate. Do not edit the generated file by hand. | L |
| 9 | `frontend/__tests__/components.test.tsx:41-50` | 4 `react/display-name` lint errors on the `jest.mock` component stubs. | Give the stubs named functions. | L |

### Tier 2: duplication and smells (low–medium risk)

| # | File:line | Issue | Metric | Proposed fix | Risk |
|---|---|---|---|---|---|
| 10 | `backend/firestore/writer.py:127` `_message_doc` / `:175` `append_conversation_turn` | The same 17 keyword parameters are declared twice, and lines 132-146 duplicate lines 180-194. | 17 params ×2, 15-line clone | Have `append_conversation_turn` forward `**fields` to `_message_doc`, or group them in a `TypedDict`. Firestore document shape unchanged. | M |
| 11 | `frontend/app/page.tsx:384-387, 407-440` | Tab rendering is a 6-branch ternary chain, and hidden tabs are a hardcoded `if` inside `.map`. | RsDocumentPanel CC 17 | Use a `VISIBLE_TABS` list and a tab → panel lookup object. | L |
| 12 | `frontend/app/page.tsx` (1,481 lines) | God module: 8 components (`MessageBubble`, `RsDocumentPanel`, `HistorySidebar`, `ChatHeader`, `ChatInput`, `SessionRatingModal`, `FinalizingOverlay` usage, `ChatPage`) in one file. | MessageBubble CC 26 / 222 lines; ChatInput CC 21 / 213 lines; ChatPage 333 lines | Move each sub-component to `app/components/` as is (pure moves first, one commit each). Then reduce `MessageBubble` and `ChatInput` complexity with guard clauses and extracted subcomponents. | M |
| 13 | `frontend/app/components/FieldCard.tsx:20` | Nested ternaries for source label, border class and badge. | CC 29, 125 lines | Use a `SOURCE_LABELS` lookup table and extract `SuggestionBar`. | M |
| 14 | `frontend/lib/api.ts:45` `dispatchSseEvent` | Long `if` chain over SSE event types. | CC 18 | Use a handler map keyed by event type. | M |
| 15 | `frontend/app/components/RsLiveTemplate.tsx:217`, `app/i18n/LocaleContext.tsx:34` | 2 `react-hooks/set-state-in-effect` lint errors. | — | LocaleContext: use a lazy `useState` initialiser reading `localStorage` (guarded for SSR). RsLiveTemplate: derive the value during render instead. | M |

### Tier 3: complexity in backend logic (medium risk; add tests first)

These are the functions with cyclomatic complexity above 10. Those marked *untested* get characterisation tests before any change.

| # | File:line | Metric | Tests today | Proposed fix | Risk |
|---|---|---|---|---|---|
| 16 | `backend/firestore/writer.py:552` `compose_rs_field_view` | CC 24, depth 4, 68 lines | 1 file | Extract a per-field `_compose_field(key, discovery, state)` and use guard clauses. | M |
| 17 | `backend/answer_classifier.py:166` `_classify_with_llm` | CC 23, 75 lines | **untested** | Split into prompt building, LLM call and result parsing/validation. Test the parser with fixed JSON payloads. | M |
| 18 | `backend/agent/discovery_agent.py:269` `sync_workflow_with_discovery_state` | CC 19 | 5 files | Use early returns, and extract the per-field reconciliation. | M |
| 19 | `backend/api/discovery.py:105` `context_extract` | CC 15, 140 lines | **untested** | Move logic into a service function in `chat_classification`/`discovery_agent`; keep the route thin. | M |
| 20 | `backend/chat_turn.py:286` `run_turn_postprocessing` | 102 lines, 10 params | 1 file | Introduce a `TurnContext` dataclass to carry the shared parameters. | M |
| 21 | `backend/chat_classification.py:108,166,65` | 11 / 9 / 9 params, depth 4 | **untested** | Use the same `TurnContext` as #20. | M |
| 22 | `backend/chat_turn.py:129` `prepare_workflow_turn` | CC 13, 98 lines | 2 files | Extract the phase-specific context building. | M |
| 23 | `backend/chat_streaming.py:182` `chat_stream_event_generator` | CC 12, 95 lines | **untested** | Extract the event → SSE mapping. | M |
| 24 | `backend/agent/research_agent.py:58` `search_past_analyses` | CC 14 | **untested** | Use guard clauses and extract a scoring helper. | M |
| 25 | `backend/generation/pdf_export.py:106` `_parse_markdown_to_flowables` | CC 15 | 1 file | Use a line-prefix → handler lookup table. | M |
| 26 | `backend/session_bridge.py:70`, `config.py:53`, `firestore/writer.py:267` | CC 12 / 11 / 12 | mixed | Guard clauses only. | L |

### Tier 4: needs your decision (not started)

| # | Item | Why it needs a decision |
|---|---|---|
| D1 | **Hidden BPMN, Data and Analysis tabs** (`page.tsx:385`). `BpmnPanel.tsx` and `DataflowPanel.tsx` can't be reached from the UI, and about 260 of their ~360 lines are duplicates of each other. Their backend routes (`/bpmn/*`, `/dataflow/*`) and the `bpmn/` and `dataflow/` packages are still live. | If the hiding is temporary, merge the two panels into one `DiagramPanel` (high value, M risk). If it's permanent, delete the panels, and decide separately whether the backend routes stay. I won't refactor code that may be deleted. |
| D2 | **`PATCH /discovery/{id}/fields`** (`api/discovery.py:293`) plus `DirectFieldsPatch`. The frontend stopped calling it (I removed the dead client function in `55e14a0`); `patch_rs_field_state` replaced it. | It's public API surface; other clients or scripts may call it. Delete it or keep it? |
| D3 | **`streamChat` in `frontend/lib/api.ts:136`** has 14 positional parameters, most of them optional callbacks. | Switching to an options object is a cleaner interface but changes the call signature, which `page.tsx` and the tests depend on. It's internal to the frontend, but it is an interface change. |
| D4 | **Reserved config**: `MODEL_RESEARCH`, `AUDIO_REGION` (`config.py:87,99`) and `FINAL_ANALYSIS_SCHEMA` (`agent/finalizer_agent.py:393`, a reference-only dict). | Documented as "reserved / not yet wired". Delete them, or keep them as documentation? |
| D5 | **Red-team detector gaps**: 5 phrasings dropped from the suite in `7e2beb7`. One is a regex near-miss: `api[_ -]?key\b` doesn't match "API **keys**". | Widening the patterns is a security behaviour change, not a refactor. Track it as a separate issue. |

## Out of scope / not changing

- **FastAPI routes, Pydantic fields, python-docx attributes and ADK callback parameters** that vulture reports as unused are framework-invoked false positives.
- **`frontend/app/generated/rsSchema.ts`** is only changed through the generator (#8).
- **Long React components flagged only for length** (`AnalysisPanel`, `FileUpload`, the audio hooks) are mostly JSX markup. Splitting them adds files without reducing logic, so I'm skipping them unless they also show up for complexity.
- **Commented-out code**: none found.

## Execution rules (Phase 2)

- One logical change per commit. Run both test suites after each one, and fix or revert before moving on.
- Before touching any function in Tier 3 marked untested, I add characterisation tests and commit them separately.
- Public interfaces (HTTP routes, Firestore document shapes, generated schema contents, exported frontend API) stay unchanged unless one of D1–D4 approves a change.
- No new dependencies. radon and vulture are installed in the local venv only and were not added to `requirements.txt`.
