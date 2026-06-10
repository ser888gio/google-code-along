"""Session-scoped resource endpoints — listings, history, analyses, uploads."""

from __future__ import annotations

import asyncio

from config import GCS_PREFIX_SESSIONS
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from firestore import (
    get_conversation_history,
    get_final_analysis,
    get_srs_fields,
    list_sessions,
)
from gcs import get_bucket_name, list_files, write_file
from logger import get_logger
from pydantic import BaseModel
from utils import sanitize_gcs_filename, sanitize_gcs_segment

logger = get_logger(__name__)

router = APIRouter(tags=["sessions"])


class UploadResponse(BaseModel):
    gcs_path: str
    filename: str


class SessionUpload(BaseModel):
    filename: str
    gcs_path: str


class SessionUploadsResponse(BaseModel):
    session_id: str
    files: list[SessionUpload]


class FirestoreDataResponse(BaseModel):
    session_id: str
    data: dict | None = None


class SessionSummary(BaseModel):
    session_id: str
    updated_at: str | None = None
    preview: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    """Upload a file to GCS under sessions/{session_id}/{filename}."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is missing")

    try:
        safe_session_id = sanitize_gcs_segment(session_id, field_name="session_id")
        safe_filename = sanitize_gcs_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    destination = f"{GCS_PREFIX_SESSIONS}/{safe_session_id}/{safe_filename}"
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"File exceeds maximum allowed size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."),
        )
    logger.info(f"Upload received: file={safe_filename} size={len(contents)}B session_id={safe_session_id}")
    gcs_path = write_file(
        path=destination,
        data=contents,
        content_type=file.content_type or "application/octet-stream",
    )
    logger.debug(f"File uploaded to GCS: {gcs_path}")
    return UploadResponse(gcs_path=gcs_path, filename=safe_filename)


@router.get("/uploads/{session_id}", response_model=SessionUploadsResponse)
async def session_uploads(session_id: str):
    """List files stored in GCS under sessions/{session_id}/."""
    try:
        safe_session_id = sanitize_gcs_segment(session_id, field_name="session_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    prefix = f"{GCS_PREFIX_SESSIONS}/{safe_session_id}/"
    try:
        paths = list_files(prefix=prefix)
    except Exception as exc:
        logger.error(
            f"Failed to list session uploads: session_id={safe_session_id} error={exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not list uploaded files for this session.",
        ) from exc

    bucket_name = get_bucket_name()
    files = [
        SessionUpload(
            filename=path.split("/")[-1],
            gcs_path=f"gs://{bucket_name}/{path}",
        )
        for path in paths
        if path.split("/")[-1]
    ]
    return SessionUploadsResponse(session_id=safe_session_id, files=files)


@router.get("/sessions", response_model=list[SessionSummary])
async def sessions_list():
    """Return a summary list of all stored sessions."""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, list_sessions)
    return items


@router.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Return the full conversation history for *session_id*."""
    loop = asyncio.get_running_loop()
    messages = await loop.run_in_executor(None, get_conversation_history, session_id)
    return HistoryResponse(session_id=session_id, messages=messages)


# TODO: add AnalysisResponse model once final_analysis schema is finalized
#       (mirrors FINAL_ANALYSIS_SCHEMA in agent/finalizer_agent.py)


@router.get("/analyses/{session_id}")
async def get_analysis(session_id: str):
    """Return the finalized analysis for a session, or status if still pending.

    The frontend polls this endpoint every 5 s after receiving the
    "finalizing" SSE event.

    Returns:
      {"status": "not_found"}                          — finalization never triggered
      {"status": "pending"}                            — run_finalizer() still running
      {"status": "error"}                              — pipeline failed
      {"status": "complete", "analysis": {...}}        — done, full analysis included
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, get_final_analysis, session_id)

    if result is None:
        return {"status": "not_found"}

    status = result.get("finalization_status", "not_found")

    if status == "complete":
        result.pop("finalization_status", None)
        logger.info(f"Analysis ready: session_id={session_id}")
        return {"status": "complete", "analysis": result}

    logger.debug(f"Analysis poll: session_id={session_id} status={status}")
    return {"status": status}


@router.get("/firestore/data/{session_id}", response_model=FirestoreDataResponse)
async def firestore_data(session_id: str):
    """Return the latest SRS data stored in Firestore for *session_id*.

    The frontend polls this endpoint after each turn to refresh the right panel.
    Returns data=null if no document has been written yet.
    """
    try:
        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(None, get_srs_fields, session_id)
    except Exception as exc:
        logger.error(
            f"Firestore read failed: event=firestore_unavailable_total session_id={session_id} {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}")
    return FirestoreDataResponse(session_id=session_id, data=doc)
