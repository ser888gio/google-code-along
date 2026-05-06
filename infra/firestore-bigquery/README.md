# Firestore to BigQuery Export

Phase 4 keeps chat data in one Firestore session document with a `messages`
array. Install one Firebase `firestore-bigquery-export` extension instance for
the configured `FIRESTORE_COLLECTION`, then create `messages_view.sql` as the
replay-friendly view used by dashboards/admin queries.

Recommended settings:

- Firestore retention: 90 days for conversation documents.
- BigQuery retention: 1 year.
- Downstream materialized/reporting tables should partition by `created_at`
  daily and cluster by `session_id`.
- Keep feedback as a separate top-level collection with its own extension
  instance when Phase 5 is implemented.

Smoke query:

```sql
SELECT session_id, COUNT(*) AS message_count, SUM(cost_usd) AS cost_usd
FROM `PROJECT_ID.observability.messages`
GROUP BY 1
ORDER BY message_count DESC
LIMIT 10;
```
