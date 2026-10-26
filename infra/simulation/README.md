# User Simulation Job

Synthetic users (LLM personas) interview with the deployed RS assistant through
the same HTTP calls the frontend makes. Every simulated session lands in
Firestore, OTel metrics, BigQuery and the Monitoring dashboard like real
traffic. Code: `backend/observability/simulation/run_simulation.py`.

All simulated data is tagged: session IDs start with `sim-`, user IDs are
`sim-u01` … `sim-u40`.

## What is simulated

- **40 users**, each with a fixed persona (12 types, Czech and English) and a
  department. Their projects come from that department (~30 business scenarios).
- **User intent** is the only configured input (`SIM_INTENT_MIX`):
  `finish` 80 %, `early_exit` 15 % (quits after 2–6 turns), `disconnect` 5 %
  (drops the stream mid-reply).
- **Success is measured**, not configured: whether a session reaches a finished
  specification is decided by the real backend.
- A user who rated a session 1–2 does not come back (churn), which drives the
  retention metrics.

## Deploy

CI (`.github/workflows/cicd.yaml`) deploys the job on every backend push to
`develop` and creates the Cloud Scheduler trigger if it is missing. The manual
steps below do the same thing outside CI.

The job runs the backend image, so the simulator code must first reach
`develop` (CI builds and deploys the backend image on push). Then run these in
Cloud Shell or any bash with `gcloud`. They read the image, URL and service
account from the live backend service.

```bash
PROJECT=vw-skda-fskoda-sandbox-jzf
REGION=europe-west4
SERVICE=business-persona-ai-backend
gcloud config set project $PROJECT

IMAGE=$(gcloud run services describe $SERVICE --region=$REGION --format='value(spec.template.spec.containers[0].image)')
URL=$(gcloud run services describe $SERVICE --region=$REGION --format='value(status.url)')
SA=$(gcloud run services describe $SERVICE --region=$REGION --format='value(spec.template.spec.serviceAccountName)')

# 1. Create (or update) the job.
gcloud run jobs deploy rs-user-simulation \
  --region=$REGION --image=$IMAGE --service-account=$SA \
  --command=python --args=-m,observability.simulation.run_simulation \
  --set-env-vars="^|^SIM_TARGET_URL=$URL|SIM_RUN_PROBABILITY=0.6|SIM_MAX_START_DELAY_S=3000|SIM_INTENT_MIX=finish:0.8,early_exit:0.15,disconnect:0.05" \
  --set-secrets=GOOGLE_API_KEY=GOOGLE_API_KEY:latest,GCS_BUCKET_NAME=GCS_BUCKET_NAME:latest \
  --task-timeout=2h --max-retries=0

# 2. Test one chat now (forced run, no delay) and watch it in the logs.
gcloud run jobs execute rs-user-simulation --region=$REGION --wait \
  --update-env-vars=SIM_RUN_PROBABILITY=1,SIM_MAX_START_DELAY_S=0

# 3. Let Cloud Scheduler trigger it. The scheduler's account needs permission to run the job.
gcloud run jobs add-iam-policy-binding rs-user-simulation --region=$REGION \
  --member="serviceAccount:$SA" --role=roles/run.invoker

gcloud scheduler jobs create http rs-user-simulation \
  --location=$REGION \
  --schedule="0 8-16 * * 1-5" \
  --time-zone="Europe/Prague" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/rs-user-simulation:run" \
  --http-method=POST \
  --oauth-service-account-email=$SA
```

The job fires every hour from 08:00 to 16:00 Prague time. Each trigger runs a
chat with probability 0.6, after a random 0–50 min delay. That averages about 5
chats per working day: ~54 in 2 weeks, ~81 in 3. Pause it when you have enough:

```bash
gcloud scheduler jobs pause rs-user-simulation --location=europe-west4
```

Local run against a local backend (results go to `backend/sim_results/`):

```powershell
cd backend
$env:SIM_TARGET_URL = "http://localhost:8080"
.\.venv\Scripts\python.exe -m observability.simulation.run_simulation
```

## Where to see the metrics

1. **Thesis numbers: `summary.json` and `sessions.csv`.** Download the per-session
   results and aggregate them:

   ```bash
   BUCKET=$(gcloud secrets versions access latest --secret=GCS_BUCKET_NAME)
   mkdir -p backend/sim_results
   gcloud storage cp "gs://$BUCKET/simulations/*.json" backend/sim_results/
   cd backend
   python -m observability.simulation.run_simulation report sim_results
   ```

   `report` writes `sessions.csv` (one row per session, ready for Excel and
   charts) and `summary.json` (all metrics below, overall and per persona). It
   can be re-run at any time during the 2–3 weeks.
2. **Live progress: Cloud Logging.** Filter
   `resource.type="cloud_run_job" AND textPayload:"rs.sim.session"`. Each line
   shows the user, intent, outcome, turns and rating.
3. **System view: the Cloud Monitoring dashboard** (`infra/monitoring/`). The
   simulated traffic feeds the existing OTel metrics: session completions,
   feedback votes, TTFT, cost and completeness. These metrics don't carry a
   session tag, so they mix with any real traffic in the same period.
4. **Raw data: BigQuery** `observability.messages` and `observability.feedback`,
   filtered with `session_id LIKE 'sim-%'` (see the cost query below).

## Metrics

Grouped by Google's HEART framework. The numbers in brackets are the metrics
from the o2ods article "14 must-have metrics for measuring user interaction
with AI chatbots".

| HEART | Metric | `summary.json` key |
|---|---|---|
| Happiness | CSAT (#14) | `csat_mean`, `csat_pct_4_or_5`, `rating_distribution` |
| Happiness | Satisfaction / sentiment (#10) | `sentiment_shares`, `thumbs_up_ratio` |
| Engagement | Interaction volume, duration, interactions (#1, #2, #5, #11) | `sessions`, `mean_messages_per_session`, `mean_duration_min` |
| Adoption | Total users (#3) | `total_users` |
| Retention | Sessions per user, retention rate (#4, #12) | `sessions_per_user`, `retention_rate` |
| Task success | Resolution rate (#6) | `resolution_rate_finish_intent` (headline), `resolution_rate_all` |
| Task success | Drop-out rate (#9) | `dropout_rate` |
| Task success | Conversion rate (#13): RS DOCX downloaded | `conversion_rate` |
| Task success | Response time (#8) | `mean_ttft_ms`, `p95_latency_ms`, `mean_time_to_analysis_s` |
| — | Transfer to humans (#7) | Not applicable: the tool has no human handoff |

RS-specific: `mean_accepted_completeness`, `goal_achieved_rate`,
`business_focus_rate` (the assistant did not choose technology for the user),
`error_rate`, `turn_cap_rate`. Like CSAT, `goal_achieved_rate` and
`business_focus_rate` count only sessions with a verdict: disconnected users
never see the rating dialog.

Cost per simulated session from BigQuery:

```sql
SELECT session_id, COUNT(*) AS messages, SUM(cost_usd) AS cost_usd
FROM `PROJECT_ID.observability.messages`
WHERE session_id LIKE 'sim-%'
GROUP BY 1
ORDER BY cost_usd DESC;
```

## Methodological caveat

Ratings, thumbs and sentiment come from LLM personas, not humans, and the
intent mix is an assumption. Present the results as a *simulated
pre-production evaluation*. The resolution rate, latency, completeness and
error rate are measured from the real system.
