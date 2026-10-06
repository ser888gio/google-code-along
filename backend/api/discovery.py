"""Live RS discovery endpoints — 22-field extraction and direct field edits."""

from __future__ import annotations

import asyncio
import weakref

import runtime
from agent.discovery_agent import extract_discovery_fields
from chat_classification import solution_type_value
from config import APP_NAME
from fastapi import APIRouter, HTTPException
from firestore import (
    accept_rs_fields,
    clear_accepted_rs_fields,
    compose_rs_field_view,
    dismiss_rs_field_suggestions,
    get_discovery_state,
    get_rs_field_state,
    upsert_discovery_state,
    upsert_srs_fields,
)
from generation import compile_srs_json_from_session
from logger import get_logger
from observability.safety import (
    FRIENDLY_COST_ERROR,
    CostCircuitBreakerTripped,
    assert_session_within_budget,
)
from pydantic import BaseModel
from utils import extract_conversation_text

logger = get_logger(__name__)

router = APIRouter(tags=["discovery"])


class ContextRequest(BaseModel):
    session_id: str
    user_id: str = "default_user"


class FieldData(BaseModel):
    filled: bool
    value: str | None
    source: str | None = None  # "user" | "ai" | "upload" | null
    status: str | None = None
    accepted: dict | None = None
    suggestion: dict | None = None
    dismissed_suggestions: list[str] = []


class ContextResponse(BaseModel):
    completeness: int
    accepted_completeness: int = 0
    discovery_completeness: int = 0
    fields: dict[str, FieldData]


class DirectFieldsPatch(BaseModel):
    fields: dict[str, str]


class RsFieldStatePatch(BaseModel):
    action: str
    fields: dict[str, str] | None = None
    keys: list[str] | None = None
    source: str | None = None


# Per-session dedup lock for /context/extract.
# Prevents multiple parallel Gemini extraction calls for the same session
# (common in voice mode where turn_complete events arrive faster than
# the ~40s extraction call can finish).
# WeakValueDictionary so entries are evicted automatically once no request
# holds a reference to the lock — no unbounded growth across sessions.
_extract_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


async def _persist_srs_to_firestore(session_id: str, user_id: str) -> None:
    """Compile the full SRS JSON and upsert it into Firestore.

    Runs in the background — failures are logged and never surface to the user.
    """
    try:
        srs_json = await compile_srs_json_from_session(
            session_service=runtime.session_service,
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if srs_json:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, upsert_srs_fields, session_id, srs_json)
            logger.debug(f"SRS persisted to Firestore: session_id={session_id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Firestore SRS upsert failed: session_id={session_id} error={exc}")


@router.post("/context/extract", response_model=ContextResponse)
async def context_extract(req: ContextRequest):
    """Extract all 22 discovery form fields from the current conversation.

    Calls Gemini Flash to map what has been discussed into the 22-field schema.
    Always returns all 22 field keys.

    Per-session deduplication: if an extraction is already in-flight for this
    session, subsequent requests wait for that result instead of spawning
    parallel Gemini calls.  This is critical in voice mode where turn_complete
    events arrive much faster than the ~40s extraction call.

    Fallback order when the ADK session is missing (e.g. after a backend restart
    or when loading a historical session that was never replayed in ADK):
      1. Try the ADK InMemorySessionService — extract fresh from live events.
      2. If not found, return the last saved discovery state from Firestore.
      3. If nothing saved yet, return empty state (completeness=0).
    """
    sid = req.session_id
    try:
        assert_session_within_budget(sid)
    except CostCircuitBreakerTripped as exc:
        raise HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR) from exc

    try:
        session = await runtime.session_service.get_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=sid,
        )
    except Exception as exc:
        logger.error(
            f"Failed to get session for extraction: session_id={sid}: {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Session lookup failed: {type(exc).__name__}")

    if session is None:
        # ADK session gone — return last persisted discovery state if available
        try:
            loop = asyncio.get_running_loop()
            saved = await loop.run_in_executor(None, get_discovery_state, sid)
        except Exception as exc:
            logger.error(f"Firestore fallback failed for session_id={sid}: {exc}", exc_info=True)
            raise HTTPException(status_code=502, detail=f"Firestore unavailable: {type(exc).__name__}")
        if saved:
            rs_field_state = await loop.run_in_executor(None, get_rs_field_state, sid)
            logger.info(
                "ADK session missing, returning saved discovery state: "
                f"session_id={sid} "
                f"completeness={saved.get('completeness')}%"
            )
            return compose_rs_field_view(saved, rs_field_state)
        rs_field_state = await loop.run_in_executor(None, get_rs_field_state, sid)
        if rs_field_state:
            return compose_rs_field_view(None, rs_field_state)
        logger.info(f"No ADK session and no saved state for session_id={sid}")
        return compose_rs_field_view(None, None)

    # --- Per-session dedup lock ---
    # Ensure only one Gemini extraction runs per session at a time.
    # Additional callers wait for the lock and then read the freshly
    # persisted result from Firestore (avoids a second Gemini call).
    new_lock = asyncio.Lock()
    lock = _extract_locks.setdefault(sid, new_lock)
    # Keep a strong local reference so the WeakValueDictionary entry stays
    # alive for the duration of this request (del new_lock is fine here).

    if lock.locked():
        # Another extraction is already running for this session.
        # Wait for it to finish, then return the persisted result.
        logger.info(f"Extraction already in-flight, waiting for lock: session_id={sid}")
        async with lock:
            # The first caller has finished and persisted the result.
            loop = asyncio.get_running_loop()
            try:
                saved = await loop.run_in_executor(None, get_discovery_state, sid)
            except Exception as exc:
                logger.warning(f"Firestore get_discovery_state (coalesced) failed: session_id={sid} {exc}")
                saved = None
            if saved:
                rs_field_state = await loop.run_in_executor(None, get_rs_field_state, sid)
                logger.info(
                    f"Returning coalesced extraction result: session_id={sid} completeness={saved.get('completeness')}%"
                )
                return compose_rs_field_view(saved, rs_field_state)
            return compose_rs_field_view(None, None)

    async with lock:
        # Re-fetch session inside the lock to pick up events that were
        # appended between the initial get_session() and acquiring the lock
        # (e.g. SessionBridge injections that run before turn_complete).
        session = await runtime.session_service.get_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=sid,
        )
        if session is None:
            logger.warning(f"Session disappeared during extraction: session_id={sid}")
            return compose_rs_field_view(None, None)

        conversation_text = extract_conversation_text(session)
        logger.info(
            f"Conversation text for extraction: session_id={sid} "
            f"events={len(session.events)} text_len={len(conversation_text)} "
            f"preview={conversation_text[:200]!r}"
        )
        try:
            loop = asyncio.get_running_loop()
            _saved_state = await loop.run_in_executor(None, get_discovery_state, sid)
            _sol_type = solution_type_value(_saved_state)
            result = await extract_discovery_fields(conversation_text, session_id=sid, solution_type=_sol_type)
        except CostCircuitBreakerTripped as exc:
            raise HTTPException(status_code=429, detail=FRIENDLY_COST_ERROR) from exc
        logger.info(f"Discovery fields extracted: session_id={sid} completeness={result.get('completeness')}%")

        # Fire-and-forget: persist discovery state + full SRS to Firestore
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, upsert_discovery_state, sid, result)
        except Exception as exc:
            logger.warning(f"Firestore upsert_discovery_state failed: session_id={sid} {exc}")

        asyncio.create_task(
            _persist_srs_to_firestore(
                session_id=sid,
                user_id=req.user_id,
            )
        )

        # Return merged state: direct fields overlay AI-extracted fields
        try:
            merged = await loop.run_in_executor(None, get_discovery_state, sid)
        except Exception as exc:
            logger.warning(f"Firestore get_discovery_state failed: session_id={sid} {exc}")
            merged = None
        if merged:
            rs_field_state = await loop.run_in_executor(None, get_rs_field_state, sid)
            return compose_rs_field_view(merged, rs_field_state)
        rs_field_state = await loop.run_in_executor(None, get_rs_field_state, sid)
        return compose_rs_field_view(result, rs_field_state)


@router.get("/discovery/{session_id}", response_model=ContextResponse)
async def discovery_state(session_id: str):
    """Return the last saved 22-field discovery state for *session_id*.

    Used by the frontend when loading a historical session to restore the
    Preview panel without re-running Gemini extraction.
    Returns completeness=0 with empty fields if nothing has been saved yet.
    """
    loop = asyncio.get_running_loop()
    saved = await loop.run_in_executor(None, get_discovery_state, session_id)
    if saved:
        logger.debug(f"Discovery state retrieved: session_id={session_id} completeness={saved.get('completeness')}%")
    rs_field_state = await loop.run_in_executor(None, get_rs_field_state, session_id)
    if saved or rs_field_state:
        return compose_rs_field_view(saved, rs_field_state)
    logger.debug(f"No saved discovery state for session_id={session_id}")
    return compose_rs_field_view(None, None)


@router.patch("/discovery/{session_id}/rs-field-state", response_model=ContextResponse)
async def patch_rs_field_state(session_id: str, body: RsFieldStatePatch):
    """Accept, dismiss, or clear user decisions for RS fields."""
    loop = asyncio.get_running_loop()
    try:
        if body.action == "accept":
            await loop.run_in_executor(
                None,
                accept_rs_fields,
                session_id,
                body.fields or {},
                body.source or "user_manual",
            )
        elif body.action == "dismiss":
            await loop.run_in_executor(None, dismiss_rs_field_suggestions, session_id, body.fields or {})
        elif body.action == "clear":
            await loop.run_in_executor(None, clear_accepted_rs_fields, session_id, body.keys or [])
        else:
            raise HTTPException(status_code=400, detail="Unsupported RS field state action.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    discovery = await loop.run_in_executor(None, get_discovery_state, session_id)
    rs_field_state = await loop.run_in_executor(None, get_rs_field_state, session_id)
    return compose_rs_field_view(discovery, rs_field_state)


@router.patch("/discovery/{session_id}/fields", response_model=ContextResponse)
async def patch_direct_fields(session_id: str, body: DirectFieldsPatch):
    """Directly set field values, bypassing AI extraction.

    Compatibility route for older callers. Values are now stored as accepted
    RS field state so subsequent AI extraction runs never erase them.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, accept_rs_fields, session_id, body.fields, "user_manual")
    logger.info(
        f"RS field state patched via legacy direct route: session_id={session_id} keys={list(body.fields.keys())}"
    )
    discovery = await loop.run_in_executor(None, get_discovery_state, session_id)
    rs_field_state = await loop.run_in_executor(None, get_rs_field_state, session_id)
    return compose_rs_field_view(discovery, rs_field_state)
