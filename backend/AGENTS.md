# Agent Registry

All LLM components in the backend. Model constants are defined in `config.py` and all currently point to `gemini-3.1-pro-preview`.

---

## Agents (ADK `Agent` objects)

| Name | Constant | File | Model constant | Triggered by | Role |
|---|---|---|---|---|---|
| `business_analyst_orchestrator` | `rs_agent` | `agent/agent.py` | `MODEL_ORCHESTRATOR` | ADK runner on every chat turn | Main user-facing conversational agent; drives field discovery, calls research tools |
| `business_analyst_audio` | `audio_agent` | `agent/agent.py` | `MODEL_AUDIO` | WebSocket bidi voice endpoint | Same role as orchestrator but for real-time voice streaming (Live API) |
| `discovery_agent` | `discovery_agent` | `agent/discovery_agent.py` | `MODEL_DISCOVERY` | ADK AgentTool (unused directly); `extract_discovery_fields()` called from `main.py` | Extracts all 28 form fields from conversation transcript after every turn |

---

## Direct Gemini Calls (not ADK `Agent` objects)

| Component | Constant | File | Model constant | Triggered by | Role |
|---|---|---|---|---|---|
| Answer classifier | — | `answer_classifier.py` | `MODEL_DISCOVERY` | `main.py` → `classify_user_turn()` before every orchestrator turn | Classifies the user's reply as answered / deferred / clarification / not_answered; emits coverage_gaps |
| Finalizer | — | `agent/finalizer_agent.py` | `MODEL_FINALIZER` | `main.py` → `run_finalizer()` when `[FINALIZING]` detected | Synthesises conversation + knowledge base into the final structured JSON analysis |
| BPMN generator | — | `bpmn/generator.py` | `MODEL_BPMN` | `main.py` → `generate_bpmn_diagram()` | Generates BPMN XML diagram of the as-is/to-be process |
| Dataflow generator | — | `dataflow/generator.py` | `MODEL_DATAFLOW` | `main.py` → `generate_dataflow_diagram()` | Generates dataflow diagram (DFD) of the solution |
| SRS compiler | — | `generation/srs_compiler.py` | `MODEL_SRS_COMPILER` | Word/PDF export endpoints | Compiles the RS document from conversation history for Word/PDF export |

---

## Research Tools (FunctionTools, no own model)

These are plain Python functions registered as ADK `FunctionTool`s on the orchestrator. They run inside the orchestrator's context and do not make their own LLM calls.

| Tool function | File | Backed by | Role |
|---|---|---|---|
| `search_past_analyses` | `agent/research_agent.py` | GCS scan | Searches finalised past analyses stored in GCS |
| `list_knowledge_base_docs` | `agent/research_agent.py` | GCS listing | Lists available reference documents in the knowledge base bucket |
| `search_vertex_ai` | `agent/research_agent.py` | Stub (removed) | Stub — Vertex AI Search was removed; returns empty results |

---

## Call Flow (per user message)

```
User message
    │
    ├─ answer_classifier.classify_user_turn()   [MODEL_DISCOVERY — fast, per-turn]
    │       └─ solution_configs.get_field_rubric_block()  ← solution-type-aware rubric
    │
    ├─ orchestrator (rs_agent / audio_agent)    [MODEL_ORCHESTRATOR / MODEL_AUDIO]
    │       ├─ search_past_analyses()           [GCS — no LLM]
    │       ├─ list_knowledge_base_docs()       [GCS — no LLM]
    │       └─ search_vertex_ai()              [stub — no LLM]
    │
    ├─ extract_discovery_fields()               [MODEL_DISCOVERY — after the reply, via frontend POST /context/extract]
    │       └─ solution_configs.get_all_field_shapes()  ← solution-type-aware shapes
    │
    └─ [if FINALIZING detected]
            ├─ run_finalizer()                  [MODEL_FINALIZER]
            ├─ generate_bpmn_diagram()          [MODEL_BPMN]
            └─ generate_dataflow_diagram()      [MODEL_DATAFLOW]
```

---

## Model Constants (all in `config.py`)

| Constant | Current value |
|---|---|
| `MODEL_ORCHESTRATOR` | `gemini-3.1-pro-preview` |
| `ORCHESTRATOR_THINKING_LEVEL` | `low` (env-overridable; text orchestrator only) |
| `MODEL_AUDIO` | `gemini-3.1-flash-live-preview` |
| `MODEL_DISCOVERY` | `gemini-3.1-flash-lite` |
| `MODEL_FINALIZER` | `gemini-3.1-pro-preview` |
| `MODEL_BPMN` | `gemini-3.1-flash-lite` |
| `MODEL_DATAFLOW` | `gemini-3.1-flash-lite` |
| `MODEL_SRS_COMPILER` | `gemini-3.1-flash-lite` |
| `MODEL_RESEARCH` | `gemini-3.1-flash-lite` (defined but not yet wired) |
