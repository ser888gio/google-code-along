"""Admin review UI endpoints — BigQuery-backed metrics and transcripts."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Literal

from admin_sessions import (
    get_admin_metrics,
    get_admin_session,
    list_admin_sessions,
    require_admin,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from logger import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


class AdminSessionSummary(BaseModel):
    id: str
    session_id: str
    project_name: str
    message_count: int
    cost_usd: float
    dominant_feedback: str
    thumbs_down_count: int
    thumbs_up_count: int
    session_rating: int | None = None
    updated_at: str | None = None
    trace_id: str | None = None
    cloud_trace_url: str | None = None


class AdminMessageFeedback(BaseModel):
    vote: str
    comment_redacted: str | None = None


class AdminTranscriptMessage(BaseModel):
    message_id: str | None = None
    role: str
    text_redacted: str
    created_at: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    model: str | None = None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    ttft_ms: int | None = None
    itl_ms: int | None = None
    latency_ms: int | None = None
    tool_calls: list[dict]
    phase: str | None = None
    finish_reason: str | None = None
    feedback: AdminMessageFeedback | None = None
    cloud_trace_url: str | None = None


class AdminSessionDetail(BaseModel):
    id: str
    session_id: str
    project_name: str
    message_count: int
    cost_usd: float
    trace_id: str | None = None
    cloud_trace_url: str | None = None
    messages: list[AdminTranscriptMessage]


class AdminMetricsSource(BaseModel):
    messages_view: str
    feedback_view: str


class AdminMetricsSummary(BaseModel):
    sessions: int
    messages: int
    assistant_messages: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p50_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    avg_itl_ms: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    safety_finishes: int
    thumbs_up: int
    thumbs_down: int
    avg_session_rating: float | None = None


class AdminModelMetric(BaseModel):
    model: str
    phase: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    safety_finishes: int


class AdminDailyMetric(BaseModel):
    date: str
    sessions: int
    assistant_messages: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    avg_ttft_ms: float | None = None
    p95_latency_ms: float | None = None


class AdminMetricsResponse(BaseModel):
    window_days: int
    generated_at: str
    source: AdminMetricsSource
    summary: AdminMetricsSummary
    by_model: list[AdminModelMetric]
    daily: list[AdminDailyMetric]


@router.get("/admin/metrics", response_model=AdminMetricsResponse)
async def admin_metrics(
    _: None = Depends(require_admin),
    days: int = Query(default=7, ge=1, le=90),
):
    """Return BigQuery-backed LLM observability aggregates for the admin UI."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, partial(get_admin_metrics, days=days))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Admin metrics query failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not query admin metrics from BigQuery.",
        ) from exc


@router.get("/admin/sessions", response_model=list[AdminSessionSummary])
async def admin_sessions_list(
    _: None = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    filter: Literal["thumbs_down"] | None = None,
):
    """Return BigQuery session summaries for the self-hosted review UI."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            partial(list_admin_sessions, limit=limit, filter_value=filter),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Admin sessions query failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Could not query admin sessions from BigQuery.",
        ) from exc


@router.get("/admin/sessions/{session_id}", response_model=AdminSessionDetail)
async def admin_session_detail(
    session_id: str,
    _: None = Depends(require_admin),
):
    """Return a full BigQuery transcript for the self-hosted review UI."""
    loop = asyncio.get_running_loop()
    try:
        detail = await loop.run_in_executor(None, get_admin_session, session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Admin session detail query failed: session_id={session_id} error={exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not query admin session from BigQuery.",
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail
