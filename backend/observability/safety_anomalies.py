"""Emit metrics for sessions flagged by the BigQuery anomaly scheduled query."""

from __future__ import annotations

import hashlib
import logging
import os
import re

logger = logging.getLogger(__name__)

_TABLE_ID_RE = re.compile(
    r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"
)


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def anomaly_reason(*, token_anomaly: bool, cost_anomaly: bool) -> str:
    if token_anomaly and cost_anomaly:
        return "tokens_and_cost"
    if token_anomaly:
        return "tokens"
    if cost_anomaly:
        return "cost"
    return "unknown"


def _configured_table_id() -> str:
    table_id = os.getenv("SAFETY_ANOMALIES_TABLE", "").strip()
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    dataset = os.getenv("BIGQUERY_DATASET", "observability").strip()
    if not table_id and project:
        table_id = f"{project}.{dataset}.safety_anomalous_sessions"
    if not table_id:
        raise RuntimeError(
            "SAFETY_ANOMALIES_TABLE is not configured and GOOGLE_CLOUD_PROJECT "
            "is empty."
        )
    if not _TABLE_ID_RE.fullmatch(table_id):
        raise RuntimeError(
            "SAFETY_ANOMALIES_TABLE must be project.dataset.table with only "
            "letters, numbers, underscores, or hyphens."
        )
    return table_id


def _lookback_hours() -> int:
    raw = os.getenv("SAFETY_ANOMALIES_LOOKBACK_HOURS", "36")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "SAFETY_ANOMALIES_LOOKBACK_HOURS must be an integer."
        ) from exc
    return max(1, min(value, 168))


def run() -> int:
    from google.cloud import bigquery

    from logger import setup_logging
    from observability.tracing import setup_telemetry

    setup_logging()
    setup_telemetry()

    from observability.metrics import force_flush_metrics, record_anomalous_session

    table_id = _configured_table_id()
    lookback_hours = _lookback_hours()
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None
    client = bigquery.Client(project=project)

    query = f"""
    SELECT
      session_id,
      token_anomaly,
      cost_anomaly,
      total_tokens,
      cost_usd,
      flagged_at
    FROM `{table_id}`
    WHERE flagged_at >= TIMESTAMP_SUB(
      CURRENT_TIMESTAMP(),
      INTERVAL @lookback_hours HOUR
    )
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY session_id
      ORDER BY flagged_at DESC
    ) = 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "lookback_hours",
                "INT64",
                lookback_hours,
            )
        ]
    )

    rows = list(client.query(query, job_config=job_config).result())
    for row in rows:
        reason = anomaly_reason(
            token_anomaly=bool(row.token_anomaly),
            cost_anomaly=bool(row.cost_anomaly),
        )
        record_anomalous_session(reason=reason)
        logger.warning(
            "Anomalous session flagged: "
            f"event=rs.safety.anomalous_session "
            f"session_id_hash={_hash_id(str(row.session_id))} "
            f"reason={reason} total_tokens={int(row.total_tokens or 0)} "
            f"cost_usd={float(row.cost_usd or 0.0):.6f}"
        )

    force_flush_metrics()
    logger.info(
        "Safety anomaly metric sync complete: "
        f"source_table={table_id} lookback_hours={lookback_hours} rows={len(rows)}"
    )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
