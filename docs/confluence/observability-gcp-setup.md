# GCP Observability Setup

This guide explains how to set up and inspect observability for the RS Generator in Google Cloud. It complements `docs/confluence/observability.md` with the practical console and CLI steps developers usually need while operating the deployed Cloud Run backend.

## What Is Exported

The backend initializes OpenTelemetry in `backend/main.py` through `setup_telemetry(app)`. The implementation is in `backend/observability/tracing.py`.

When the backend runs on Cloud Run with valid Google Cloud credentials, it exports:

| Signal | GCP destination | Main use |
|---|---|---|
| FastAPI request spans | Cloud Trace | Request timing and trace/log correlation |
| ADK and model spans | Cloud Trace | Model call timing and attributes |
| OpenTelemetry custom metrics | Cloud Monitoring | Latency, token, cost, session, feedback, and safety charts |
| Structured logs | Cloud Logging | Runtime errors and workflow events |
| Log-based metrics | Cloud Monitoring | Events detected from logs |
| Firestore export views | BigQuery | Offline session, feedback, cost, and safety analysis |

## Required GCP Setup

Enable the observability APIs:

```bash
gcloud services enable \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com \
  --project=vw-skda-fskoda-sandbox-jzf
```

The Cloud Run backend runtime service account needs:

```text
roles/monitoring.metricWriter
roles/cloudtrace.agent
roles/logging.logWriter
```

The project deployment docs also recommend these broader runtime roles for the application:

```text
roles/datastore.user
roles/storage.objectAdmin
roles/secretmanager.secretAccessor
roles/bigquery.jobUser
```

## Where Metrics Appear

OpenTelemetry custom metrics appear in Cloud Monitoring under:

```text
workload.googleapis.com/<metric_name>
```

For this project, useful metrics include:

| Metric type | Resource | Meaning |
|---|---|---|
| `workload.googleapis.com/genai.client.ttft_seconds` | Generic Task | Time to first streamed token |
| `workload.googleapis.com/genai.client.itl_seconds` | Generic Task | Inter-token latency |
| `workload.googleapis.com/genai.client.operation.duration_seconds` | Generic Task | End-to-end model operation duration |
| `workload.googleapis.com/genai.client.token.usage` | Generic Task | Input, output, cache-read, and cache-write tokens |
| `workload.googleapis.com/genai.client.cost_usd` | Generic Task | Estimated model cost |
| `workload.googleapis.com/rs.cache.hit_ratio` | Generic Task | Cache-read tokens divided by input tokens |
| `workload.googleapis.com/rs.feedback.vote` | Generic Task | User feedback votes |
| `workload.googleapis.com/rs.session.completion_total` | Generic Task | Finalized or abandoned session count |
| `workload.googleapis.com/rs.session.duration_seconds` | Generic Task | Session duration |
| `workload.googleapis.com/rs.safety.finish_reason_safety` | Generic Task | Gemini responses stopped by safety |
| `workload.googleapis.com/rs.safety.cost_circuit_tripped` | Generic Task | Sessions stopped by cost limit |
| `workload.googleapis.com/rs.safety.injection_attempt_total` | Generic Task | Prompt-injection or exfiltration attempts |

Cloud Run platform metrics appear separately, for example:

```text
run.googleapis.com/request_count
```

Use resource type:

```text
Cloud Run Revision
```

and filter by:

```text
service_name = business-persona-ai-backend
```

Log-based metrics appear under:

```text
logging.googleapis.com/user/<metric_name>
```

Current log-based metrics:

```text
logging.googleapis.com/user/firestore_unavailable_total
logging.googleapis.com/user/bridge_injection_failure_total
```

## Metrics Explorer Gotcha

In the Google Cloud console, **Metrics Explorer** often defaults to showing only active metrics. If you search for `workload` and nothing appears, turn off:

```text
Active metrics only
```

Then search for exact metric names such as:

```text
genai.client.ttft_seconds
genai.client.cost_usd
rs.cache.hit_ratio
```

The resource type for OpenTelemetry custom metrics is usually:

```text
Generic Task
```

If `Generic Task` is missing from the picker, first verify that Cloud Monitoring has received metric descriptors.

## Verify Metric Descriptors

Cloud Shell might not support `gcloud monitoring metrics descriptors` in every installed gcloud surface. The REST API works reliably:

```bash
curl -s -G "https://monitoring.googleapis.com/v3/projects/vw-skda-fskoda-sandbox-jzf/metricDescriptors" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  --data-urlencode 'filter=metric.type=starts_with("workload.googleapis.com/")' \
  | jq -r '["TYPE", "METRIC_KIND", "VALUE_TYPE"], (.metricDescriptors[]? | [.type, .metricKind, .valueType]) | @tsv' \
  | column -t
```

If this returns metric rows, OpenTelemetry export has reached Cloud Monitoring at least once.

If it returns nothing:

1. Send fresh traffic through the deployed backend.
2. Wait 1-3 minutes.
3. Check backend logs for exporter startup.
4. Confirm the Cloud Run runtime service account has `roles/monitoring.metricWriter`.

## Check Exporter Startup Logs

Use Cloud Logging:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="business-persona-ai-backend" AND ("Cloud Monitoring exporter configured" OR "Cloud Monitoring exporter disabled")' \
  --project=vw-skda-fskoda-sandbox-jzf \
  --limit=20 \
  --format='table(timestamp,textPayload,jsonPayload.message)'
```

Expected successful log:

```text
Cloud Monitoring exporter configured for OpenTelemetry metrics.
```

If the log says `Cloud Monitoring exporter disabled`, inspect the same log line for the exception. The usual causes are missing credentials, missing API enablement, or missing metric writer permission.

## Create The Dashboard

The repository includes a Cloud Monitoring dashboard definition:

```text
infra/monitoring/dashboard.json
```

The checked-in dashboard is intentionally conservative. It charts metrics that are emitted by normal chat traffic and uses text panels for optional UX, safety, and quality metrics that might not have descriptors yet in a fresh project. This avoids `Cannot find metric(s)` errors before flows like feedback, finalization, safety blocking, or anomaly jobs have run.

From Cloud Shell or a local checkout:

```bash
cd google-code-along/infra/monitoring
sed -i 's/BACKEND_SERVICE_NAME/business-persona-ai-backend/g' dashboard.json

gcloud monitoring dashboards create \
  --project=vw-skda-fskoda-sandbox-jzf \
  --config-from-file=dashboard.json
```

If the dashboard already exists in GCP, creating a new one will not update the old dashboard. Update the existing dashboard instead:

```bash
DASHBOARD_ID=$(gcloud monitoring dashboards list \
  --project=vw-skda-fskoda-sandbox-jzf \
  --filter='displayName="RS Generator - Phase 6 SLIs"' \
  --format='value(name)' \
  | head -n 1)

gcloud monitoring dashboards update "$DASHBOARD_ID" \
  --project=vw-skda-fskoda-sandbox-jzf \
  --config-from-file=dashboard.json
```

The GitHub Actions deployment workflow also updates this dashboard automatically when `infra/monitoring/dashboard.json` changes on `develop`. It replaces `BACKEND_SERVICE_NAME` with `business-persona-ai-backend`, finds the existing dashboard named `RS Generator - Phase 6 SLIs`, updates it if present, and creates it if missing.

The GitHub Actions deploy service account must have permission to manage Monitoring dashboards. Use one of:

```text
roles/monitoring.dashboardEditor
roles/monitoring.editor
```

Then open:

```text
Google Cloud Console -> Monitoring -> Dashboards
```

Look for:

```text
RS Generator - Phase 6 SLIs
```

## Build A Dashboard Manually

In Google Cloud:

```text
Monitoring -> Dashboards -> Create dashboard
```

Recommended panels:

| Panel | Metric | Resource | Group by | Aggregation |
|---|---|---|---|---|
| TTFT p95 | `workload.googleapis.com/genai.client.ttft_seconds` | Generic Task | `model`, `phase` | 95th percentile |
| Operation duration p95 | `workload.googleapis.com/genai.client.operation.duration_seconds` | Generic Task | `operation`, `status` | 95th percentile |
| Token usage | `workload.googleapis.com/genai.client.token.usage` | Generic Task | `model`, `feature`, `type` | sum or rate |
| Estimated model cost | `workload.googleapis.com/genai.client.cost_usd` | Generic Task | `model`, `feature` | sum or rate |
| Cache hit ratio | `workload.googleapis.com/rs.cache.hit_ratio` | Generic Task | `model` | mean |
| Cloud Run request rate | `run.googleapis.com/request_count` | Cloud Run Revision | service | rate |

## MQL Examples

MQL can be easier than the visual metric picker when custom metrics are hard to find.

TTFT p95:

```mql
fetch generic_task
| metric 'workload.googleapis.com/genai.client.ttft_seconds'
| align delta(1m)
| every 1m
| group_by [metric.model, metric.phase],
    [p95: percentile(value.genai_client_ttft_seconds, 95)]
```

Operation duration p95:

```mql
fetch generic_task
| metric 'workload.googleapis.com/genai.client.operation.duration_seconds'
| align delta(1m)
| every 1m
| group_by [metric.operation, metric.status],
    [p95: percentile(value.genai_client_operation_duration_seconds, 95)]
```

Token usage:

```mql
fetch generic_task
| metric 'workload.googleapis.com/genai.client.token.usage'
| align delta(1m)
| every 1m
| group_by [metric.model, metric.feature, metric.type],
    [tokens: sum(value.genai_client_token_usage)]
```

Cost:

```mql
fetch generic_task
| metric 'workload.googleapis.com/genai.client.cost_usd'
| align rate(1h)
| every 1h
| group_by [metric.model, metric.feature],
    [usd_per_hour: sum(value.genai_client_cost_usd)]
```

## PromQL Examples

Google Cloud also supports PromQL for Cloud Monitoring charts. Metric names are transformed:

```text
workload.googleapis.com/genai.client.ttft_seconds
```

becomes:

```text
workload_googleapis_com_genai_client_ttft_seconds
```

Distribution metrics are exposed as Prometheus-style histograms. Use the `_bucket` suffix for percentile queries.

TTFT p95:

```promql
histogram_quantile(
  0.95,
  sum by (le, model, phase) (
    rate(workload_googleapis_com_genai_client_ttft_seconds_bucket[1m])
  )
)
```

If the Cloud Monitoring dashboard editor asks the chart to support dashboard-level grouping, include the Google Cloud dashboard macro:

```promql
histogram_quantile(
  0.95,
  sum by (le, model, phase, ${__groupby}) (
    rate(workload_googleapis_com_genai_client_ttft_seconds_bucket[1m])
  )
)
```

The `${__groupby}` macro is Google Cloud dashboard syntax, not standard PromQL. It lets dashboard-level grouping controls inject selected labels into the query.

## Why Some Panels Are Empty

Custom metric descriptors are created only after the application sends the first data point. Some metrics require specific user flows:

| Metric | How to trigger it |
|---|---|
| `genai.client.ttft_seconds` | Send streamed chat messages |
| `genai.client.token.usage` | Send messages that trigger Gemini calls |
| `genai.client.cost_usd` | Send messages that produce non-zero model cost |
| `rs.feedback.vote` | Submit thumbs-up, thumbs-down, or session feedback |
| `rs.session.completion_total` | Finalize or abandon a session |
| `rs.safety.cost_circuit_tripped` | Exceed the configured session cost circuit breaker |
| `rs.safety.injection_attempt_total` | Send text caught by deterministic safety checks |
| `rs.safety.anomalous_session` | Run the anomaly metric job |

If a dashboard panel says it cannot find a metric, check whether the descriptor exists with the REST query above. If the descriptor is missing, the flow has not emitted that metric yet or the code path is not currently active.

## Fix Distribution Panel Errors

Some Cloud Monitoring widgets can fail if they try to apply a percentile aligner directly to a cumulative distribution metric. If a dashboard panel errors with an invalid aligner:

1. Edit the widget.
2. Set alignment to `delta`.
3. Set cross-series aggregation to the desired reducer:
   - 95th percentile for latency distributions.
   - Sum for token usage.
4. Group by the relevant metric labels.

For histogram percentiles, MQL or PromQL charts are often clearer than the visual builder.

## Trace Explorer

Open:

```text
Google Cloud Console -> Trace -> Trace Explorer
```

Filter for the backend service:

```text
business-persona-ai-backend
```

Traces show FastAPI request spans and model-related spans when requests have passed through the backend. From Logs Explorer, trace-correlated log entries can also link back to Trace details.

## Logs Explorer

Open:

```text
Google Cloud Console -> Logging -> Logs Explorer
```

Useful filters:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="business-persona-ai-backend"
```

Exporter startup:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="business-persona-ai-backend"
("Cloud Monitoring exporter configured" OR "Cloud Monitoring exporter disabled")
```

Firestore availability:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="business-persona-ai-backend"
"event=firestore_unavailable_total"
```

Voice bridge injection:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="business-persona-ai-backend"
"event=bridge_injection_failure_total"
```

## BigQuery Observability

Offline observability uses Firestore-to-BigQuery views:

```text
infra/firestore-bigquery/messages_view.sql
infra/firestore-bigquery/feedback_view.sql
```

Expected view names:

```text
vw-skda-fskoda-sandbox-jzf.observability.messages
vw-skda-fskoda-sandbox-jzf.observability.feedback
```

Use these for redacted transcript review, token and cost analysis, feedback summaries, trace links, daily trends, and session-level safety review.

## Quick Troubleshooting Checklist

If metrics do not show up:

1. Turn off `Active metrics only` in Metrics Explorer.
2. Search exact metric names, not only `workload`.
3. Confirm descriptors exist with the REST query.
4. Confirm the backend emitted fresh traffic and wait 1-3 minutes.
5. Check exporter startup logs.
6. Confirm `roles/monitoring.metricWriter` on the Cloud Run backend service account.
7. Confirm `monitoring.googleapis.com` and `cloudtrace.googleapis.com` are enabled.
8. Check whether the specific metric requires a flow that has not happened yet, such as feedback, finalization, or safety blocking.
