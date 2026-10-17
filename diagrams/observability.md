# Observability & Safety Architecture

Observability spans four levels: **traces** (OpenTelemetry → Cloud Trace), **metrics** (OTel → Cloud Monitoring), **structured logs** (→ log-based metrics), and **BigQuery views** for offline analysis.

## Turn pipeline

1. **Safety preflight** (`observability/safety.py`) — checks each user prompt for injection/exfiltration/jailbreak patterns and enforces the per-session **cost circuit breaker** (`COST_CIRCUIT_BREAKER_USD`, default $5).
2. **ADK callbacks** (`observability/callbacks.py`) — `before_model_cb` stamps the active span (model, session, hashed user, agent) and adds a redacted prompt event; `after_model_cb` records finish reason, token counts, cache reads, estimated cost, and latency; tool callbacks record tool spans.
3. **Instrumentation** — `metrics.py` defines OTel metrics (`genai.client.ttft_seconds`, `token.usage`, `cost_usd`, `rs.safety.*`, `rs.session.*`, `rs.feedback.vote`); `tracing.py` initializes exporters; `privacy/redactor.py` redacts previews.

## Backends

- **Cloud Trace** — request/model spans with GenAI attributes.
- **Cloud Monitoring** — `workload.googleapis.com/*` custom metrics feed the dashboard and alert policies (`infra/monitoring/`).
- **Cloud Logging** — structured logs feed **log-based metrics**: `firestore_unavailable_total`, `bridge_injection_failure_total`.
- **Firestore → BigQuery** — redacted messages/metrics export to `messages_view` / `feedback_view` for transcript, cost, latency, and feedback review.

## Safety jobs (`infra/safety/`)

- **Red-team job** (`redteam-job.yaml`) records `rs.safety.injection_block_rate` (target: block 100% of known-bad prompts).
- **Anomaly job** (`anomaly-metric-job.yaml` + `anomalous_sessions.sql`) flags suspicious token/cost sessions via `rs.safety.anomalous_session`.

**Caveat:** cost-circuit state is in process memory and resets on backend restart.
