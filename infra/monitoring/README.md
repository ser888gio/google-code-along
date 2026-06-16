# Phase 6 Monitoring

Phase 6 adds the app-side OTel metrics plus checked-in Cloud Monitoring setup
artifacts for dashboards, alert policies, and log-based metrics.

## Apply

Replace `PROJECT_ID`, `BACKEND_SERVICE_NAME`, and notification channel IDs in
the files before applying.

```bash
gcloud logging metrics create extract_timeout_total \
  --description="Pre-stream discovery extraction timed out" \
  --log-filter='resource.type="cloud_run_revision" AND textPayload:"event=extract_timeout_total"'

gcloud logging metrics create firestore_unavailable_total \
  --description="Firestore was unavailable to the backend" \
  --log-filter='resource.type="cloud_run_revision" AND textPayload:"event=firestore_unavailable_total"'

gcloud logging metrics create bridge_injection_failure_total \
  --description="Voice transcript injection into the text session failed" \
  --log-filter='resource.type="cloud_run_revision" AND textPayload:"event=bridge_injection_failure_total"'

gcloud monitoring dashboards create --config-from-file=dashboard.json
gcloud alpha monitoring policies create --policy-from-file=alert-policies.yaml
```

## Metric Names

The Google Cloud OTel exporter writes custom metrics under
`workload.googleapis.com/<metric_name>`, for example:

- `workload.googleapis.com/genai.client.ttft_seconds`
- `workload.googleapis.com/genai.client.operation.duration_seconds`
- `workload.googleapis.com/rs.session.completion_total`
- `workload.googleapis.com/rs.discovery.field.completeness_ratio`
- `workload.googleapis.com/rs.finalization.status_total`

Log-based metrics are available as `logging.googleapis.com/user/<metric_name>`.

## Notes

The dashboard includes placeholder tiles for quality and safety signals that are
listed in the Phase 6 plan but are not yet emitted by the product. Keep those
tiles as roadmap markers or remove them until the corresponding evaluators are
implemented.
