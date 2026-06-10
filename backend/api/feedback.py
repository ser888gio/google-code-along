"""User feedback endpoints — per-message thumbs and whole-session ratings."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Literal

import runtime
from fastapi import APIRouter, HTTPException
from firestore import (
    update_feedback_comment,
    upsert_message_feedback,
    upsert_session_feedback,
)
from logger import get_logger
from observability.metrics import record_feedback_vote
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    vote: Literal["up", "down"]
    comment: str | None = None


class FeedbackCommentRequest(BaseModel):
    session_id: str
    comment: str | None = None


class SessionFeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str | None = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Persist thumbs feedback for a saved assistant message."""
    loop = asyncio.get_running_loop()
    feedback = None
    for attempt in range(4):
        try:
            feedback = await loop.run_in_executor(
                None,
                partial(
                    upsert_message_feedback,
                    session_id=req.session_id,
                    message_id=req.message_id,
                    vote=req.vote,
                    comment=req.comment,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if feedback is not None:
            break
        if attempt < 3:
            await asyncio.sleep(0.4)

    if feedback is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")

    phase = str(feedback.get("phase") or "chat")
    record_feedback_vote(vote=req.vote, phase=phase)
    logger.info(
        "User feedback recorded: "
        f"event=user_feedback session_id={req.session_id} "
        f"message_id={req.message_id} vote={req.vote} phase={phase}"
    )
    return {"status": "ok"}


@router.patch("/feedback/{message_id}")
async def patch_feedback(message_id: str, req: FeedbackCommentRequest):
    """Attach or replace the free-text comment on an existing feedback vote."""
    loop = asyncio.get_running_loop()
    feedback = await loop.run_in_executor(
        None,
        partial(
            update_feedback_comment,
            session_id=req.session_id,
            message_id=message_id,
            comment=req.comment,
        ),
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")

    logger.info(
        "User feedback comment updated: "
        f"event=user_feedback_comment session_id={req.session_id} "
        f"message_id={message_id}"
    )
    return {"status": "ok"}


@router.post("/feedback/session")
async def submit_session_feedback(req: SessionFeedbackRequest):
    """End a chat session and persist its overall conversation rating."""
    loop = asyncio.get_running_loop()
    try:
        feedback = await loop.run_in_executor(
            None,
            partial(
                upsert_session_feedback,
                session_id=req.session_id,
                rating=req.rating,
                comment=req.comment,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if feedback is None:
        raise HTTPException(status_code=404, detail="Session not found")

    runtime.record_session_outcome(req.session_id, "abandoned")
    record_feedback_vote(vote=f"rating_{req.rating}", phase="session")
    logger.info(f"Session feedback recorded: event=session_feedback session_id={req.session_id} rating={req.rating}")
    return {"status": "ok"}
