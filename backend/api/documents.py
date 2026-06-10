"""RS document generation and export endpoints (markdown, PDF, DOCX)."""

from __future__ import annotations

import asyncio
import time

import runtime
from config import APP_NAME, GCS_PREFIX_SESSIONS
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from firestore import get_direct_fields
from gcs import get_bucket_name, write_file
from generation import (
    compile_rs_from_session,
    compile_srs_json_from_session,
    markdown_to_pdf,
    rs_template_to_docx,
    srs_json_to_docx,
)
from logger import get_logger
from observability.metrics import record_operation_duration
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(tags=["documents"])


class SessionRef(BaseModel):
    session_id: str
    user_id: str = "default_user"


class DocumentResponse(BaseModel):
    markdown: str | None
    ready: bool


@router.post("/document", response_model=DocumentResponse)
async def get_document(req: SessionRef):
    """Extract the generated RS document from a session.

    Returns the markdown if [GENERATE_RS] was found in the conversation,
    otherwise returns ready=False.
    """
    t0 = time.perf_counter()
    markdown = await compile_rs_from_session(
        session_service=runtime.session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.compile",
        status="ready" if markdown is not None else "not_ready",
    )
    return DocumentResponse(
        markdown=markdown,
        ready=markdown is not None,
    )


@router.post("/document/pdf")
async def download_pdf(req: SessionRef):
    """Download the RS document as a PDF.

    Extracts the RS markdown from the session and converts it to PDF.
    Returns 404 if no document has been generated yet.
    """
    t0 = time.perf_counter()
    status = "ok"
    markdown = await compile_rs_from_session(
        session_service=runtime.session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if markdown is None:
        status = "not_ready"
        record_operation_duration(
            time.perf_counter() - t0,
            model="none",
            operation="document.pdf",
            status=status,
        )
        logger.warning(f"PDF export requested but no RS document found: session_id={req.session_id}")
        raise HTTPException(
            status_code=404,
            detail="No RS document found. Complete the conversation first.",
        )

    logger.info(f"Generating PDF export: session_id={req.session_id}")
    pdf_bytes = markdown_to_pdf(markdown)
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.pdf",
        status=status,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=requirement_specification.pdf"},
    )


@router.post("/document/docx")
async def download_docx(req: SessionRef):
    """Generate and download the SRS as a populated Word (.docx) document.

    Uses Gemini to compile the full SRS structure from the conversation,
    then writes it into a Word document using the SRS template structure.
    Returns 404 if the session is not found, 422 if compilation fails.
    """
    t0 = time.perf_counter()
    status = "ok"
    srs_json = await compile_srs_json_from_session(
        session_service=runtime.session_service,
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if srs_json is None:
        status = "compile_failed"
        record_operation_duration(
            time.perf_counter() - t0,
            model="none",
            operation="document.docx",
            status=status,
        )
        logger.warning(f"DOCX export failed — SRS could not be compiled: session_id={req.session_id}")
        raise HTTPException(
            status_code=422,
            detail="Could not compile SRS from the conversation. Keep chatting to provide more details.",
        )

    logger.info(f"Generating DOCX export: session_id={req.session_id}")
    docx_bytes = srs_json_to_docx(srs_json)
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.docx",
        status=status,
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=requirement_specification.docx"},
    )


@router.post("/document/rs-template/docx")
async def download_rs_template_docx(req: SessionRef):
    """Generate a Word doc from the 22 RSLiveTemplate fields.

    Save to GCS and return it for download.
    """
    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    # Use only user-confirmed direct fields as the source of truth.
    # AI-extracted values are never written to the document unless the user
    # explicitly accepted them in the Preview.
    direct = await loop.run_in_executor(None, get_direct_fields, req.session_id)
    fields: dict = {
        key: {"filled": True, "value": value, "source": "user"}
        for key, value in direct.items()
        if value and str(value).strip()
    }

    docx_bytes = rs_template_to_docx(fields)

    gcs_path = f"{GCS_PREFIX_SESSIONS}/{req.session_id}/rs_template.docx"
    await loop.run_in_executor(
        None,
        lambda: write_file(
            gcs_path,
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    logger.info(f"RS template DOCX saved to GCS: {gcs_path}")
    record_operation_duration(
        time.perf_counter() - t0,
        model="none",
        operation="document.rs_template_docx",
        status="ok",
    )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename=rs_template.docx",
            "X-GCS-Path": f"gs://{get_bucket_name()}/{gcs_path}",
        },
    )
