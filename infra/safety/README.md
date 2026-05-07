# Phase 9 Safety

Artifacts for the red-team job, cost circuit breaker, and anomalous session
detection.

## Cost Circuit Breaker

Set `COST_CIRCUIT_BREAKER_USD` on the backend Cloud Run service. The default is
`5.0`; set `0` to disable the in-process guard.

## Red-Team Job

Replace placeholders in `redteam-job.yaml`, deploy the job, and schedule it:

```bash
gcloud run jobs replace infra/safety/redteam-job.yaml --region=REGION

gcloud scheduler jobs create http rs-redteam-daily \
  --schedule="0 2 * * *" \
  --uri="https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT_ID/jobs/rs-redteam-daily:run" \
  --http-method=POST \
  --oauth-service-account-email=SERVICE_ACCOUNT@PROJECT_ID.iam.gserviceaccount.com
```

Manual verification:

```bash
REDTEAM_TARGET_URL=https://BACKEND_STAGING_URL \
python -m observability.redteam.run_redteam
```

The job records `workload.googleapis.com/rs.safety.injection_block_rate` with
`suite=daily_known_bad` and fails when the block rate is below 100%.

## BigQuery Anomaly Query

Create a scheduled query from `anomalous_sessions.sql` after replacing
`PROJECT_ID` and `DATASET`.

Deploy `anomaly-metric-job.yaml` with the same placeholders replaced and
schedule it to run after the BigQuery scheduled query:

```bash
gcloud run jobs replace infra/safety/anomaly-metric-job.yaml --region=REGION

gcloud scheduler jobs create http rs-safety-anomaly-metrics \
  --schedule="30 2 * * *" \
  --uri="https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT_ID/jobs/rs-safety-anomaly-metrics:run" \
  --http-method=POST \
  --oauth-service-account-email=SERVICE_ACCOUNT@PROJECT_ID.iam.gserviceaccount.com
```

The job reads rows from `DATASET.safety_anomalous_sessions`, records
`workload.googleapis.com/rs.safety.anomalous_session`, and logs
`event=rs.safety.anomalous_session` for each flagged session.
