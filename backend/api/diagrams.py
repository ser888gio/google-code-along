"""Mermaid diagram generation endpoints — BPMN and Data Flow."""

from __future__ import annotations

import time

import runtime
from bpmn import check_completeness, generate_bpmn_diagram
from config import APP_NAME, MODEL_ORCHESTRATOR
from dataflow import check_dfd_completeness, generate_dataflow_diagram
from fastapi import APIRouter, HTTPException
from logger import get_logger
from observability.metrics import record_operation_duration
from pydantic import BaseModel
from utils import extract_conversation_text

logger = get_logger(__name__)

router = APIRouter(tags=["diagrams"])


class BpmnRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class BpmnResponse(BaseModel):
    ready: bool
    mermaid: str | None = None
    score: int | None = None
    missing: list[str] | None = None


class DataflowRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class DataflowResponse(BaseModel):
    ready: bool
    mermaid: str | None = None
    score: int | None = None
    missing: list[str] | None = None


@router.post("/bpmn/generate", response_model=BpmnResponse)
async def bpmn_generate(req: BpmnRequest):
    """Check RS completeness and generate a Mermaid BPMN diagram if ≥ 90%."""
    t0 = time.perf_counter()
    session = await runtime.session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = extract_conversation_text(session)

    completeness = await check_completeness(conversation_text)
    score: int = completeness.get("score", 0)
    missing: list[str] = completeness.get("missing", [])
    logger.info(f"BPMN completeness check: session_id={req.session_id} score={score}%")

    if score < 90:
        logger.debug(f"BPMN not ready (score < 90): missing={missing}")
        record_operation_duration(
            time.perf_counter() - t0,
            model=MODEL_ORCHESTRATOR,
            operation="diagram.bpmn",
            status="not_ready",
        )
        return BpmnResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating BPMN diagram: session_id={req.session_id}")
    mermaid = await generate_bpmn_diagram(conversation_text)
    record_operation_duration(
        time.perf_counter() - t0,
        model=MODEL_ORCHESTRATOR,
        operation="diagram.bpmn",
        status="ok",
    )
    return BpmnResponse(ready=True, mermaid=mermaid, score=score)


@router.post("/dataflow/generate", response_model=DataflowResponse)
async def dataflow_generate(req: DataflowRequest):
    """Check DFD readiness and generate a Mermaid Data Flow Diagram if score ≥ 70%."""
    t0 = time.perf_counter()
    session = await runtime.session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=req.session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    conversation_text = extract_conversation_text(session)

    completeness = await check_dfd_completeness(conversation_text)
    score: int = completeness.get("score", 0)
    missing: list[str] = completeness.get("missing", [])
    logger.info(f"Dataflow completeness check: session_id={req.session_id} score={score}%")

    if score < 70:
        logger.debug(f"Dataflow not ready (score < 70): missing={missing}")
        record_operation_duration(
            time.perf_counter() - t0,
            model=MODEL_ORCHESTRATOR,
            operation="diagram.dataflow",
            status="not_ready",
        )
        return DataflowResponse(ready=False, score=score, missing=missing)

    logger.info(f"Generating Dataflow diagram: session_id={req.session_id}")
    mermaid = await generate_dataflow_diagram(conversation_text)
    record_operation_duration(
        time.perf_counter() - t0,
        model=MODEL_ORCHESTRATOR,
        operation="diagram.dataflow",
        status="ok",
    )
    return DataflowResponse(ready=True, mermaid=mermaid, score=score)
