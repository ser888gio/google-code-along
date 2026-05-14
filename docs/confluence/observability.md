# Observability Guide

## Overview

The RS Generator has observability at four levels:

- Request and model traces through OpenTelemetry and Cloud Trace.
- Custom metrics through OpenTelemetry and Cloud Monitoring.
- Structured application logs from FastAPI, workflow, safety, Firestore, GCS, and voice paths.
- Admin review data through Firestore-to-BigQuery views.

The goal is to answer:

- Is the app healthy?
- Are users completing sessions?
- Are model calls slow, expensive, or blocked by safety?
- Are extraction, finalization, Firestore, GCS, or voice paths failing?
- Which sessions need human review?

---

## Observability Surfaces

| Surface | Used for | Source |
|---|---|---|
| Cloud Run logs | Runtime errors, warnings, workflow events, safety blocks, voice errors | Backend logger |
| Cloud Trace | Request spans, ADK model spans, GenAI attributes, trace links | OpenTelemetry |
| Cloud Monitoring | Latency, cost, token, safety, session, feedback metrics | OpenTelemetry exporter |
| Log-based metrics | Events detected from logs, such as extraction timeout or bridge injection failure | Cloud Logging metrics |
| BigQuery admin views | Redacted transcript review, cost/tokens per message, feedback | Firestore export views |
| Admin UI | Human-friendly metrics and session review pages | Backend admin endpoints |

---

## OpenTelemetry Setup

Telemetry is initialized in `backend/main.py` through:

```python
setup_telemetry(app)
```

Implementation lives in:

```text
backend/observability/tracing.py
```

Behavior:

- FastAPI is instrumented automatically.
- On Cloud Run, Cloud Trace and Cloud Monitoring exporters are configured when credentials are available.
- In local development, exporter setup can fail gracefully; the app still runs.
- The OpenTelemetry resource uses:
  - `K_SERVICE` as service name, defaulting to `rs-generator-backend`.
  - `K_REVISION` as service version, defaulting to `local`.

Cloud Run injects trace context, so request logs and traces can be correlated in GCP.

---

## Model Callback Instrumentation

ADK model callbacks live in:

```text
backend/observability/callbacks.py
```

They are intended to be wired into ADK agents as:

```python
before_model_callback=before_model_cb
after_model_callback=after_model_cb
before_tool_callback=before_tool_cb
after_tool_callback=after_tool_cb
```

### Before Model Call

The callback stamps the active span with:

| Attribute | Meaning |
|---|---|
| `gen_ai.system` | Always `gemini`. |
| `gen_ai.request.model` | Requested model. |
| `session_id` | Current session ID. |
| `user_id_hash` | Hashed user ID. |
| `agent_name` | ADK agent name. |

It also adds a short truncated user-message span event.

### After Model Call

The callback records:

- Response model.
- Finish reason.
- Input tokens.
- Output tokens.
- Cache read tokens.
- Cache write tokens.
- Estimated cost.
- Model operation duration.
- Safety finish counter when finish reason indicates safety.
- Per-turn model-call summary for Firestore persistence.

### Tool Calls

Tool callbacks record span events and per-turn summaries for:

- Tool call start.
- Tool call result.
- Short redacted argument/result previews.

---

## Custom Metrics

Metric definitions live in:

```text
backend/observability/metrics.py
```

In Cloud Monitoring, OpenTelemetry custom metrics appear under:

```text
workload.googleapis.com/<metric_name>
```

### Latency Metrics

| Metric | Type | Attributes | Meaning |
|---|---|---|---|
| `genai.client.ttft_seconds` | Histogram | `model`, `phase` | Time to first streamed token. |
| `genai.client.itl_seconds` | Histogram | none | Average inter-token latency. |
| `genai.client.operation.duration_seconds` | Histogram | `model`, `operation`, `status` | End-to-end operation duration. |
| `rs.session.duration_seconds` | Histogram | `outcome` | Session duration until finalized or abandoned. |

### Token And Cost Metrics

| Metric | Type | Attributes | Meaning |
|---|---|---|---|
| `genai.client.token.usage` | Histogram | `model`, `type`, `feature` | Input, output, cache-read, or cache-write token count. |
| `genai.client.cost_usd` | Counter | `model`, `feature`, `session_id_hash` | Estimated model cost. |
| `rs.cache.hit_ratio` | Observable gauge | `model` | Cache-read tokens divided by input tokens. |

### Product And Quality Metrics

| Metric | Type | Attributes | Meaning |
|---|---|---|---|
| `rs.feedback.vote` | Counter | `vote`, `phase` | Message thumbs or session rating. |
| `rs.session.completion_total` | Counter | `outcome` | Finalized or abandoned sessions. |

### Safety Metrics

| Metric | Type | Attributes | Meaning |
|---|---|---|---|
| `rs.safety.finish_reason_safety` | Counter | `model` | Gemini response ended due to safety. |
| `rs.safety.cost_circuit_tripped` | Counter | `session_id_hash` | Session exceeded configured cost limit. |
| `rs.safety.injection_attempt_total` | Counter | `blocked`, `category` | Deterministic prompt-injection or exfiltration pattern detected. |
| `rs.safety.injection_block_rate` | Observable gauge | `suite` | Red-team suite block rate. |
| `rs.safety.anomalous_session` | Counter | `reason` | Sessions flagged by anomaly detection. |

---

## Log-Based Metrics

Some important events are easiest to detect from logs. The checked-in setup is in:

```text
infra/monitoring/README.md
infra/monitoring/log-based-metrics.yaml
```

Current log-based metrics:

| Metric | Log event | Meaning |
|---|---|---|
| `extract_timeout_total` | `event=extract_timeout_total` | Pre-stream discovery extraction exceeded the timeout. |
| `firestore_unavailable_total` | `event=firestore_unavailable_total` | Backend could not read/write Firestore. |
| `bridge_injection_failure_total` | `event=bridge_injection_failure_total` | Voice transcript injection into text ADK session failed. |

Manual creation example:

```bash
gcloud logging metrics create extract_timeout_total \
  --description="Pre-stream discovery extraction timed out" \
  --log-filter='resource.type="cloud_run_revision" AND textPayload:"event=extract_timeout_total"'
```

Log-based metrics appear under:

```text
logging.googleapis.com/user/<metric_name>
```

---

## Admin Metrics

Admin metrics are served by:

```text
GET /admin/metrics?days=7
```

The endpoint queries BigQuery-backed views and returns:

- Session count.
- Message count.
- Assistant message count.
- Input, output, and cache-read tokens.
- Estimated cost.
- TTFT and latency aggregates.
- Safety finish count.
- Thumbs up/down.
- Average session rating.
- Per-model breakdown.
- Daily trend rows.

Frontend page:

```text
frontend/app/admin/metrics/page.tsx
```

Backend implementation:

```text
backend/admin_sessions.py
```

---

## Admin Session Review

Session review endpoints:

```text
GET /admin/sessions
GET /admin/sessions?filter=thumbs_down
GET /admin/sessions/{session_id}
```

They are backed by BigQuery views defined in:

```text
infra/firestore-bigquery/messages_view.sql
infra/firestore-bigquery/feedback_view.sql
```

Session detail includes:

- Redacted transcript.
- Message IDs.
- Trace IDs and Cloud Trace URLs.
- Model name.
- Token counts.
- Estimated cost.
- TTFT, inter-token latency, total latency.
- Tool calls.
- Phase and finish reason.
- Message feedback.

This is the main place to review low-quality sessions, repeated-question loops, safety issues, and high-cost interactions.

---

## Safety And Cost Controls

Safety guardrails live in:

```text
backend/observability/safety.py
```

### Prompt Safety

Before chat execution, the backend checks user text for known-bad patterns:

- Prompt injection.
- Prompt extraction.
- Data exfiltration.
- Jailbreak attempts.
- Obfuscated secret extraction.
- PII extraction.
- Role injection.

If blocked:

- The request returns a friendly refusal message.
- `rs.safety.injection_attempt_total` is recorded.
- Logs include `event=rs.safety.prompt_injection_blocked`.

### Cost Circuit Breaker

The per-session cost circuit breaker is configured with:

```text
COST_CIRCUIT_BREAKER_USD
```

Default:

```text
5.0
```

Set to `0` to disable the in-process guard.

If a session exceeds the limit:

- Backend raises `CostCircuitBreakerTripped`.
- Chat returns a friendly cost-limit message.
- `rs.safety.cost_circuit_tripped` is recorded.
- Logs include `event=rs.safety.cost_circuit_tripped`.

Important limitation: the circuit tracks cost in process memory. A backend restart resets the in-memory cumulative cost map.

---

## Red-Team And Anomaly Jobs

Safety artifacts live in:

```text
infra/safety/
```

### Red-Team Job

The red-team job runs known-bad prompts against a target backend and records:

```text
workload.googleapis.com/rs.safety.injection_block_rate
```

Manual local run:

```bash
REDTEAM_TARGET_URL=https://BACKEND_STAGING_URL \
python -m observability.redteam.run_redteam
```

The suite should block 100 percent of known-bad prompts.

### Anomalous Session Detection

The BigQuery query:

```text
infra/safety/anomalous_sessions.sql
```

flags suspicious sessions based on token or cost behavior.

The anomaly metric job records:

```text
workload.googleapis.com/rs.safety.anomalous_session
```

and logs:

```text
event=rs.safety.anomalous_session
```

---

## Dashboard And Alerts

Dashboard and alert artifacts:

```text
infra/monitoring/dashboard.json
infra/monitoring/alert-policies.yaml
```

Apply after replacing project, service, and notification-channel placeholders:

```bash
gcloud monitoring dashboards create --config-from-file=infra/monitoring/dashboard.json
gcloud alpha monitoring policies create --policy-from-file=infra/monitoring/alert-policies.yaml
```

Recommended dashboard sections:

- Cloud Run request rate and error rate.
- Chat TTFT and total latency.
- Model token usage by model and feature.
- Estimated model cost.
- Session finalization vs abandonment.
- Safety blocks and cost circuit trips.
- Firestore errors.
- Extraction timeouts.
- Voice bridge injection failures.
- Feedback trend and thumbs-down sessions.

---

## Operational Triage

### Chat Is Slow

Check:

1. `genai.client.ttft_seconds` by model and phase.
2. `genai.client.operation.duration_seconds` for `generate_content`.
3. Cloud Run CPU/memory/concurrency.
4. Logs for pre-stream extraction timeouts.
5. Token counts for unusually large prompts.

Likely causes:

- Large conversation context.
- Slow model response.
- Discovery extraction running before stream.
- Cloud Run cold starts.

### Preview Panel Does Not Update

Check:

1. Logs for `event=extract_timeout_total`.
2. `POST /context/extract` status in browser network tools.
3. Firestore write/read errors.
4. Cost circuit breaker logs.
5. Whether the backend restarted and lost live ADK session state.

### Finalization Does Not Complete

Check:

1. `GET /analyses/{session_id}` status.
2. Logs for `[FINALIZING] detected`.
3. Firestore `finalization_status`.
4. GCS write permissions for `analyses/{session_id}/final_analysis.json`.
5. Cost circuit events during finalizer extraction.

### Admin Pages Fail

Check:

1. Admin authorization header or IAP configuration.
2. `ADMIN_BEARER_TOKEN`.
3. BigQuery dataset/table/view names.
4. Firestore-to-BigQuery export freshness.
5. Backend logs for `Could not query admin metrics from BigQuery`.

### Voice Mode Fails

Check:

1. WebSocket connection to `/ws/{user_id}/{session_id}`.
2. Browser microphone permission and secure context.
3. Logs for `[WS] Gemini Live API error`.
4. Logs/metric for `bridge_injection_failure_total`.
5. Whether frontend received `turn_complete`.

---

## Privacy Notes

The observability system tries to reduce sensitive data exposure:

- Message text stored for admin review is redacted by `privacy/redactor.py`.
- Original text hashes are stored for correlation without preserving raw originals.
- Trace span content is truncated before being attached as span events.
- User IDs and session IDs are hashed in some metrics.

Important caveat: logs can still include short previews or operational identifiers. Do not intentionally log full prompts, uploaded file content, secrets, or raw PII.

---

## Current Gaps

- Cost circuit state is in memory and resets after backend restart.
- Some dashboard tiles are roadmap placeholders until corresponding evaluators are implemented.
- Admin metrics depend on BigQuery export/view setup.
- Voice quality metrics are mostly log-based today; there are no dedicated audio latency or reconnect metrics yet.
- Final analysis schema is not yet generated into strongly typed frontend/admin analytics contracts.
