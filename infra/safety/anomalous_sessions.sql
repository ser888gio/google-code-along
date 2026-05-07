-- Phase 9 anomaly detection scheduled query.
-- Replace PROJECT_ID and DATASET before creating the scheduled query.
--
-- Recommended schedule: every 24 hours after the Firestore->BigQuery export
-- has caught up. Alert when this table receives new rows.

CREATE OR REPLACE TABLE `PROJECT_ID.DATASET.safety_anomalous_sessions`
PARTITION BY DATE(flagged_at)
CLUSTER BY session_id AS
WITH session_usage AS (
  SELECT
    session_id,
    MAX(created_at) AS last_seen_at,
    SUM(
      COALESCE(input_tokens, 0)
      + COALESCE(output_tokens, 0)
      + COALESCE(cache_read_tokens, 0)
    ) AS total_tokens,
    SUM(COALESCE(CAST(cost_usd AS FLOAT64), 0.0)) AS cost_usd
  FROM `PROJECT_ID.DATASET.messages`
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND role = 'assistant'
  GROUP BY session_id
),
baseline AS (
  SELECT
    AVG(total_tokens) AS avg_tokens,
    STDDEV_POP(total_tokens) AS stddev_tokens,
    AVG(cost_usd) AS avg_cost_usd,
    STDDEV_POP(cost_usd) AS stddev_cost_usd
  FROM session_usage
),
flagged AS (
  SELECT
    CURRENT_TIMESTAMP() AS flagged_at,
    s.session_id,
    s.last_seen_at,
    s.total_tokens,
    s.cost_usd,
    b.avg_tokens,
    b.stddev_tokens,
    b.avg_cost_usd,
    b.stddev_cost_usd,
    s.total_tokens > b.avg_tokens + 3 * b.stddev_tokens AS token_anomaly,
    s.cost_usd > b.avg_cost_usd + 3 * b.stddev_cost_usd AS cost_anomaly
  FROM session_usage s
  CROSS JOIN baseline b
  WHERE (
      b.stddev_tokens > 0
      AND s.total_tokens > b.avg_tokens + 3 * b.stddev_tokens
    )
    OR (
      b.stddev_cost_usd > 0
      AND s.cost_usd > b.avg_cost_usd + 3 * b.stddev_cost_usd
    )
)
SELECT *
FROM flagged;
