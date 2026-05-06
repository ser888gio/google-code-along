-- BigQuery view for Phase 5 assistant-message feedback.
--
-- Install a second Firebase firestore-bigquery-export extension instance for
-- the top-level Firestore `feedback` collection, then create this as a view
-- named `feedback`.

CREATE OR REPLACE VIEW `PROJECT_ID.observability.feedback` AS
SELECT
  JSON_VALUE(data, '$.feedback_id') AS feedback_id,
  COALESCE(JSON_VALUE(data, '$.feedback_type'), 'message') AS feedback_type,
  JSON_VALUE(data, '$.session_id') AS session_id,
  JSON_VALUE(data, '$.message_id') AS message_id,
  JSON_VALUE(data, '$.trace_id') AS trace_id,
  JSON_VALUE(data, '$.span_id') AS span_id,
  JSON_VALUE(data, '$.vote') AS vote,
  SAFE_CAST(JSON_VALUE(data, '$.rating') AS INT64) AS rating,
  JSON_VALUE(data, '$.phase') AS phase,
  JSON_VALUE(data, '$.model') AS model,
  JSON_VALUE(data, '$.comment_redacted') AS comment_redacted,
  JSON_VALUE(data, '$.comment_original_hash') AS comment_original_hash,
  SAFE_CAST(JSON_VALUE(data, '$.created_at') AS TIMESTAMP) AS created_at,
  SAFE_CAST(JSON_VALUE(data, '$.updated_at') AS TIMESTAMP) AS updated_at,
  SAFE_CAST(JSON_VALUE(data, '$.ended_at') AS TIMESTAMP) AS ended_at
FROM `PROJECT_ID.firestore_export.feedback_raw_latest`;
