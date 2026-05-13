from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from config import (
    ADMIN_BEARER_TOKEN,
    APP_ENV,
    BIGQUERY_FEEDBACK_VIEW,
    BIGQUERY_MESSAGES_VIEW,
    GCP_PROJECT,
    require_config_value,
)
from fastapi import HTTPException
from starlette.requests import Request

_TABLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_]+){1,2}$")


def require_admin(request: Request) -> None:
    """Authorize the no-SaaS admin surface with IAP or a shared bearer token."""
    iap_user = request.headers.get("x-goog-authenticated-user-email")
    if iap_user:
        return

    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if ADMIN_BEARER_TOKEN and scheme.lower() == "bearer" and token.strip() == ADMIN_BEARER_TOKEN:
        return

    if APP_ENV not in {"production", "prod", "staging"} and not ADMIN_BEARER_TOKEN:
        return

    raise HTTPException(status_code=401, detail="Admin authentication required")


def _table(name: str, value: str) -> str:
    table_id = require_config_value(name, value, "querying admin chat sessions")
    if not _TABLE_ID_RE.fullmatch(table_id):
        raise RuntimeError(f"{name} must be a simple BigQuery table id.")
    return f"`{table_id}`"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in dict(row).items()}


def _cloud_trace_url(trace_id: str | None) -> str | None:
    if not trace_id or not GCP_PROJECT:
        return None
    return f"https://console.cloud.google.com/traces/list?project={GCP_PROJECT}&tid={trace_id}"


def _project_name(first_user_message: str | None, session_id: str) -> str:
    text = (first_user_message or "").strip()
    if not text:
        return session_id
    return text[:80] + ("..." if len(text) > 80 else "")


def _dominant_feedback(row: dict[str, Any]) -> str:
    down = int(row.get("thumbs_down_count") or 0)
    up = int(row.get("thumbs_up_count") or 0)
    rating = row.get("session_rating")
    if down > up:
        return "thumbs_down"
    if up > down:
        return "thumbs_up"
    if down and up:
        return "mixed"
    if rating is not None:
        return f"rating_{rating}"
    return "none"


def _query_job_config(params: list[Any]):
    from google.cloud import bigquery

    return bigquery.QueryJobConfig(query_parameters=params)


def list_admin_sessions(
    *,
    limit: int = 50,
    filter_value: str | None = None,
) -> list[dict[str, Any]]:
    """Return BigQuery-backed admin session summaries."""
    from google.cloud import bigquery

    bounded_limit = min(max(limit, 1), 200)
    messages_table = _table("BIGQUERY_MESSAGES_VIEW", BIGQUERY_MESSAGES_VIEW)
    feedback_table = _table("BIGQUERY_FEEDBACK_VIEW", BIGQUERY_FEEDBACK_VIEW)
    thumbs_down_only = filter_value == "thumbs_down"
    where_clause = "WHERE COALESCE(f.thumbs_down_count, 0) > 0" if thumbs_down_only else ""

    query = f"""
    WITH message_sessions AS (
      SELECT
        session_id,
        COUNT(*) AS message_count,
        COALESCE(SUM(CAST(cost_usd AS FLOAT64)), 0) AS cost_usd,
        MAX(created_at) AS updated_at,
        ARRAY_AGG(
          trace_id IGNORE NULLS ORDER BY created_at DESC LIMIT 1
        )[SAFE_OFFSET(0)] AS trace_id,
        ARRAY_AGG(
          IF(role = 'user', text_redacted, NULL)
          IGNORE NULLS
          ORDER BY created_at
          LIMIT 1
        )[SAFE_OFFSET(0)] AS first_user_message
      FROM {messages_table}
      GROUP BY session_id
    ),
    feedback_sessions AS (
      SELECT
        session_id,
        COUNTIF(vote = 'down') AS thumbs_down_count,
        COUNTIF(vote = 'up') AS thumbs_up_count,
        ARRAY_AGG(
          rating IGNORE NULLS ORDER BY updated_at DESC LIMIT 1
        )[SAFE_OFFSET(0)] AS session_rating
      FROM {feedback_table}
      GROUP BY session_id
    )
    SELECT
      m.session_id,
      m.message_count,
      m.cost_usd,
      m.updated_at,
      m.trace_id,
      m.first_user_message,
      COALESCE(f.thumbs_down_count, 0) AS thumbs_down_count,
      COALESCE(f.thumbs_up_count, 0) AS thumbs_up_count,
      f.session_rating
    FROM message_sessions m
    LEFT JOIN feedback_sessions f USING (session_id)
    {where_clause}
    ORDER BY updated_at DESC
    LIMIT @limit
    """
    client = bigquery.Client(project=GCP_PROJECT or None)
    job_config = _query_job_config([bigquery.ScalarQueryParameter("limit", "INT64", bounded_limit)])
    rows = client.query(query, job_config=job_config).result()

    summaries: list[dict[str, Any]] = []
    for row in rows:
        item = _row_dict(row)
        session_id = str(item["session_id"])
        summaries.append(
            {
                "id": session_id,
                "session_id": session_id,
                "project_name": _project_name(
                    item.get("first_user_message"),
                    session_id,
                ),
                "message_count": int(item.get("message_count") or 0),
                "cost_usd": float(item.get("cost_usd") or 0),
                "dominant_feedback": _dominant_feedback(item),
                "thumbs_down_count": int(item.get("thumbs_down_count") or 0),
                "thumbs_up_count": int(item.get("thumbs_up_count") or 0),
                "session_rating": item.get("session_rating"),
                "updated_at": item.get("updated_at"),
                "trace_id": item.get("trace_id"),
                "cloud_trace_url": _cloud_trace_url(item.get("trace_id")),
            }
        )
    return summaries


def get_admin_metrics(*, days: int = 7) -> dict[str, Any]:
    """Return BigQuery-backed observability aggregates for the admin UI."""
    from google.cloud import bigquery

    bounded_days = min(max(days, 1), 90)
    messages_table = _table("BIGQUERY_MESSAGES_VIEW", BIGQUERY_MESSAGES_VIEW)
    feedback_table = _table("BIGQUERY_FEEDBACK_VIEW", BIGQUERY_FEEDBACK_VIEW)
    client = bigquery.Client(project=GCP_PROJECT or None)
    params = [bigquery.ScalarQueryParameter("days", "INT64", bounded_days)]

    summary_query = f"""
    WITH scoped AS (
      SELECT *
      FROM {messages_table}
      WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    ),
    feedback_scoped AS (
      SELECT *
      FROM {feedback_table}
      WHERE COALESCE(updated_at, created_at) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    )
    SELECT
      COUNT(DISTINCT scoped.session_id) AS sessions,
      COUNT(*) AS messages,
      COUNTIF(role = 'assistant') AS assistant_messages,
      COALESCE(SUM(CAST(input_tokens AS INT64)), 0) AS input_tokens,
      COALESCE(SUM(CAST(output_tokens AS INT64)), 0) AS output_tokens,
      COALESCE(SUM(CAST(cache_read_tokens AS INT64)), 0) AS cache_read_tokens,
      COALESCE(SUM(CAST(cost_usd AS FLOAT64)), 0) AS cost_usd,
      AVG(IF(role = 'assistant', ttft_ms, NULL)) AS avg_ttft_ms,
      APPROX_QUANTILES(IF(role = 'assistant', ttft_ms, NULL), 100)[SAFE_OFFSET(50)] AS p50_ttft_ms,
      APPROX_QUANTILES(IF(role = 'assistant', ttft_ms, NULL), 100)[SAFE_OFFSET(95)] AS p95_ttft_ms,
      AVG(IF(role = 'assistant', itl_ms, NULL)) AS avg_itl_ms,
      APPROX_QUANTILES(IF(role = 'assistant', latency_ms, NULL), 100)[SAFE_OFFSET(50)] AS p50_latency_ms,
      APPROX_QUANTILES(IF(role = 'assistant', latency_ms, NULL), 100)[SAFE_OFFSET(95)] AS p95_latency_ms,
      COUNTIF(UPPER(COALESCE(finish_reason, '')) LIKE '%SAFETY%') AS safety_finishes,
      (
        SELECT COUNTIF(vote = 'up')
        FROM feedback_scoped
        WHERE feedback_type = 'message'
      ) AS thumbs_up,
      (
        SELECT COUNTIF(vote = 'down')
        FROM feedback_scoped
        WHERE feedback_type = 'message'
      ) AS thumbs_down,
      (
        SELECT AVG(rating)
        FROM feedback_scoped
        WHERE feedback_type = 'session'
      ) AS avg_session_rating
    FROM scoped
    """
    summary_rows = list(client.query(summary_query, job_config=_query_job_config(params)).result())
    summary = _row_dict(summary_rows[0]) if summary_rows else {}

    by_model_query = f"""
    SELECT
      COALESCE(model, 'unknown') AS model,
      COALESCE(phase, 'unknown') AS phase,
      COUNT(*) AS calls,
      COALESCE(SUM(CAST(input_tokens AS INT64)), 0) AS input_tokens,
      COALESCE(SUM(CAST(output_tokens AS INT64)), 0) AS output_tokens,
      COALESCE(SUM(CAST(cache_read_tokens AS INT64)), 0) AS cache_read_tokens,
      COALESCE(SUM(CAST(cost_usd AS FLOAT64)), 0) AS cost_usd,
      AVG(ttft_ms) AS avg_ttft_ms,
      APPROX_QUANTILES(ttft_ms, 100)[SAFE_OFFSET(95)] AS p95_ttft_ms,
      AVG(latency_ms) AS avg_latency_ms,
      APPROX_QUANTILES(latency_ms, 100)[SAFE_OFFSET(95)] AS p95_latency_ms,
      COUNTIF(UPPER(COALESCE(finish_reason, '')) LIKE '%SAFETY%') AS safety_finishes
    FROM {messages_table}
    WHERE role = 'assistant'
      AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    GROUP BY model, phase
    ORDER BY cost_usd DESC, calls DESC
    LIMIT 25
    """
    by_model = [_row_dict(row) for row in client.query(by_model_query, job_config=_query_job_config(params)).result()]

    daily_query = f"""
    SELECT
      DATE(created_at) AS date,
      COUNT(DISTINCT session_id) AS sessions,
      COUNTIF(role = 'assistant') AS assistant_messages,
      COALESCE(SUM(CAST(input_tokens AS INT64)), 0) AS input_tokens,
      COALESCE(SUM(CAST(output_tokens AS INT64)), 0) AS output_tokens,
      COALESCE(SUM(CAST(cache_read_tokens AS INT64)), 0) AS cache_read_tokens,
      COALESCE(SUM(CAST(cost_usd AS FLOAT64)), 0) AS cost_usd,
      AVG(IF(role = 'assistant', ttft_ms, NULL)) AS avg_ttft_ms,
      APPROX_QUANTILES(IF(role = 'assistant', latency_ms, NULL), 100)[SAFE_OFFSET(95)] AS p95_latency_ms
    FROM {messages_table}
    WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    GROUP BY date
    ORDER BY date
    """
    daily = [_row_dict(row) for row in client.query(daily_query, job_config=_query_job_config(params)).result()]

    return {
        "window_days": bounded_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "messages_view": BIGQUERY_MESSAGES_VIEW,
            "feedback_view": BIGQUERY_FEEDBACK_VIEW,
        },
        "summary": {
            "sessions": int(summary.get("sessions") or 0),
            "messages": int(summary.get("messages") or 0),
            "assistant_messages": int(summary.get("assistant_messages") or 0),
            "input_tokens": int(summary.get("input_tokens") or 0),
            "output_tokens": int(summary.get("output_tokens") or 0),
            "cache_read_tokens": int(summary.get("cache_read_tokens") or 0),
            "cost_usd": float(summary.get("cost_usd") or 0),
            "avg_ttft_ms": summary.get("avg_ttft_ms"),
            "p50_ttft_ms": summary.get("p50_ttft_ms"),
            "p95_ttft_ms": summary.get("p95_ttft_ms"),
            "avg_itl_ms": summary.get("avg_itl_ms"),
            "p50_latency_ms": summary.get("p50_latency_ms"),
            "p95_latency_ms": summary.get("p95_latency_ms"),
            "safety_finishes": int(summary.get("safety_finishes") or 0),
            "thumbs_up": int(summary.get("thumbs_up") or 0),
            "thumbs_down": int(summary.get("thumbs_down") or 0),
            "avg_session_rating": summary.get("avg_session_rating"),
        },
        "by_model": by_model,
        "daily": daily,
    }


def get_admin_session(session_id: str) -> dict[str, Any] | None:
    """Return a full BigQuery transcript with costs, tools, feedback, and traces."""
    from google.cloud import bigquery

    messages_table = _table("BIGQUERY_MESSAGES_VIEW", BIGQUERY_MESSAGES_VIEW)
    feedback_table = _table("BIGQUERY_FEEDBACK_VIEW", BIGQUERY_FEEDBACK_VIEW)
    query = f"""
    SELECT
      m.session_id,
      m.message_id,
      m.trace_id,
      m.span_id,
      m.role,
      m.text_redacted,
      m.model,
      m.input_tokens,
      m.output_tokens,
      m.cache_read_tokens,
      CAST(m.cost_usd AS FLOAT64) AS cost_usd,
      m.ttft_ms,
      m.itl_ms,
      m.latency_ms,
      m.tool_calls,
      m.phase,
      m.finish_reason,
      m.created_at,
      f.vote AS feedback_vote,
      f.comment_redacted AS feedback_comment_redacted
    FROM {messages_table} m
    LEFT JOIN {feedback_table} f
      ON f.session_id = m.session_id
     AND f.message_id = m.message_id
     AND f.feedback_type = 'message'
    WHERE m.session_id = @session_id
    ORDER BY m.created_at, m.message_id
    """
    client = bigquery.Client(project=GCP_PROJECT or None)
    job_config = _query_job_config([bigquery.ScalarQueryParameter("session_id", "STRING", session_id)])
    rows = [_row_dict(row) for row in client.query(query, job_config=job_config).result()]
    if not rows:
        return None

    first_user = next(
        (row.get("text_redacted") for row in rows if row.get("role") == "user"),
        None,
    )
    trace_id = next(
        (row.get("trace_id") for row in reversed(rows) if row.get("trace_id")),
        None,
    )
    messages: list[dict[str, Any]] = []
    for row in rows:
        tool_calls: list[dict[str, Any]] = []
        if row.get("tool_calls"):
            try:
                parsed = json.loads(str(row["tool_calls"]))
                tool_calls = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                tool_calls = []

        feedback = None
        if row.get("feedback_vote"):
            feedback = {
                "vote": row.get("feedback_vote"),
                "comment_redacted": row.get("feedback_comment_redacted"),
            }

        messages.append(
            {
                "message_id": row.get("message_id"),
                "role": row.get("role"),
                "text_redacted": row.get("text_redacted") or "",
                "created_at": row.get("created_at"),
                "trace_id": row.get("trace_id"),
                "span_id": row.get("span_id"),
                "model": row.get("model"),
                "input_tokens": int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
                "cost_usd": float(row.get("cost_usd") or 0),
                "ttft_ms": row.get("ttft_ms"),
                "itl_ms": row.get("itl_ms"),
                "latency_ms": row.get("latency_ms"),
                "tool_calls": tool_calls,
                "phase": row.get("phase"),
                "finish_reason": row.get("finish_reason"),
                "feedback": feedback,
                "cloud_trace_url": _cloud_trace_url(row.get("trace_id")),
            }
        )

    return {
        "id": session_id,
        "session_id": session_id,
        "project_name": _project_name(first_user, session_id),
        "message_count": len(messages),
        "cost_usd": sum(message["cost_usd"] for message in messages),
        "trace_id": trace_id,
        "cloud_trace_url": _cloud_trace_url(trace_id),
        "messages": messages,
    }
