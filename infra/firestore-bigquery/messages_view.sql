-- BigQuery view for Phase 4 chat replay.
--
-- Replace the project/dataset/table names with the Firestore to BigQuery
-- extension output table for FIRESTORE_COLLECTION, then create this as a view
-- named `messages`.

CREATE OR REPLACE VIEW `PROJECT_ID.observability.messages` AS
SELECT
  JSON_VALUE(data, '$.session_id') AS session_id,
  JSON_VALUE(message, '$.message_id') AS message_id,
  JSON_VALUE(message, '$.trace_id') AS trace_id,
  JSON_VALUE(message, '$.span_id') AS span_id,
  JSON_VALUE(message, '$.role') AS role,
  JSON_VALUE(message, '$.text_redacted') AS text_redacted,
  JSON_VALUE(message, '$.text_original_hash') AS text_original_hash,
  JSON_VALUE(message, '$.model') AS model,
  SAFE_CAST(JSON_VALUE(message, '$.input_tokens') AS INT64) AS input_tokens,
  SAFE_CAST(JSON_VALUE(message, '$.output_tokens') AS INT64) AS output_tokens,
  SAFE_CAST(JSON_VALUE(message, '$.cache_read_tokens') AS INT64) AS cache_read_tokens,
  SAFE_CAST(JSON_VALUE(message, '$.cost_usd') AS NUMERIC) AS cost_usd,
  SAFE_CAST(JSON_VALUE(message, '$.ttft_ms') AS INT64) AS ttft_ms,
  SAFE_CAST(JSON_VALUE(message, '$.itl_ms') AS INT64) AS itl_ms,
  SAFE_CAST(JSON_VALUE(message, '$.latency_ms') AS INT64) AS latency_ms,
  JSON_QUERY(message, '$.tool_calls') AS tool_calls,
  JSON_VALUE(message, '$.phase') AS phase,
  JSON_VALUE(message, '$.finish_reason') AS finish_reason,
  COALESCE(
    SAFE_CAST(JSON_VALUE(message, '$.created_at') AS TIMESTAMP),
    timestamp
  ) AS created_at
FROM `PROJECT_ID.firestore_export.srs_sessions_raw_latest`,
UNNEST(JSON_QUERY_ARRAY(data, '$.messages')) AS message;
