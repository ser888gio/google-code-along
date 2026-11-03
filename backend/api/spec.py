"""Section state machine endpoints: typed events, chat/voice utterances, and snapshots."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from typing import Literal

from config import SECTION_ALLOW_TBD_ON_FINALIZE
from fastapi import APIRouter, HTTPException
from logger import get_logger
from pydantic import BaseModel
from spec_machine.document import DocumentActor, DocumentSnapshot
from spec_machine.intents import resolve_utterance
from spec_machine.model import (
    Accept,
    AgentProposalFor,
    Cancel,
    Confirm,
    Discard,
    DocumentEvent,
    DontKnow,
    Edit,
    Finalize,
    GoTo,
    HelpMe,
    MarkTbd,
    Next,
    Prev,
    Regenerate,
    Reject,
    ReloadSection,
    Reopen,
    Resume,
    Retry,
    Revise,
    SectionEvent,
    Skip,
    Submit,
    SubmitEdit,
    ToCurrent,
    UserMessage,
    WriteMyself,
    section_configs_from_schema,
)
from spec_machine.services import build_services, intent_classifier

logger = get_logger(__name__)

router = APIRouter(prefix="/spec", tags=["spec"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_DOCUMENTS = 256
# Actors are process-local, like ADK sessions; Firestore revisions catch cross-instance conflicts.
_documents: OrderedDict[str, DocumentActor] = OrderedDict()
_create_lock = asyncio.Lock()

Modality = Literal["chat", "voice"]
EventType = Literal[
    "NEXT",
    "PREV",
    "GO_TO",
    "FINALIZE",
    "REOPEN",
    "RELOAD_SECTION",
    "AGENT_PROPOSAL_FOR",
    "USER_MESSAGE",
    "WRITE_MYSELF",
    "DONT_KNOW",
    "SKIP",
    "CANCEL",
    "RETRY",
    "ACCEPT",
    "EDIT",
    "REGENERATE",
    "REJECT",
    "SUBMIT_EDIT",
    "SUBMIT",
    "HELP_ME",
    "MARK_TBD",
    "CONFIRM",
    "DISCARD",
    "REVISE",
    "RESUME",
]


class SpecEventBody(BaseModel):
    type: EventType
    section_id: str | None = None
    text: str | None = None
    value: str | None = None
    reason: str | None = None
    instruction: str | None = None
    modality: Modality = "chat"
    low_confidence: bool = False
    note: str | None = None
    open_question: str | None = None
    owner: str | None = None
    proposal: str | None = None
    rationale: str | None = None
    wait: bool = True


class UtteranceBody(BaseModel):
    text: str
    modality: Modality = "chat"
    wait: bool = True


class SpecResponse(BaseModel):
    handled: bool
    events: list[str] = []
    snapshot: dict


def _require(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise HTTPException(status_code=422, detail=f"'{field}' is required for this event type.")
    return value


def _section_event(body: SpecEventBody) -> SectionEvent:
    match body.type:
        case "USER_MESSAGE":
            return UserMessage(_require(body.text, "text"), modality=body.modality)
        case "WRITE_MYSELF":
            return WriteMyself()
        case "DONT_KNOW":
            return DontKnow()
        case "SKIP":
            return Skip()
        case "CANCEL":
            return Cancel()
        case "RETRY":
            return Retry()
        case "ACCEPT":
            return Accept()
        case "EDIT":
            return Edit()
        case "REGENERATE":
            return Regenerate(body.reason)
        case "REJECT":
            return Reject(body.reason)
        case "SUBMIT_EDIT":
            return SubmitEdit(_require(body.value, "value"))
        case "SUBMIT":
            return Submit(_require(body.value, "value"), modality=body.modality, low_confidence=body.low_confidence)
        case "HELP_ME":
            return HelpMe()
        case "MARK_TBD":
            return MarkTbd(note=body.note, open_question=body.open_question, owner=body.owner)
        case "CONFIRM":
            return Confirm()
        case "DISCARD":
            return Discard()
        case "REVISE":
            return Revise(body.instruction)
        case "RESUME":
            return Resume()
    raise HTTPException(status_code=422, detail=f"Unsupported event type: {body.type}")


def _document_event(body: SpecEventBody) -> DocumentEvent:
    match body.type:
        case "NEXT":
            return Next()
        case "PREV":
            return Prev()
        case "GO_TO":
            return GoTo(_require(body.section_id, "section_id"))
        case "FINALIZE":
            return Finalize()
        case "REOPEN":
            return Reopen()
        case "RELOAD_SECTION":
            return ReloadSection(_require(body.section_id, "section_id"))
        case "AGENT_PROPOSAL_FOR":
            return AgentProposalFor(
                _require(body.section_id, "section_id"), _require(body.proposal, "proposal"), body.rationale
            )
    return ToCurrent(_section_event(body))


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id.")


async def _get_document(session_id: str) -> DocumentActor:
    _validate_session_id(session_id)
    if (document := _documents.get(session_id)) is not None:
        _documents.move_to_end(session_id)
        return document
    async with _create_lock:
        if (document := _documents.get(session_id)) is None:
            try:
                document = await DocumentActor.load(
                    section_configs_from_schema(),
                    build_services(session_id),
                    allow_tbd_on_finalize=SECTION_ALLOW_TBD_ON_FINALIZE,
                )
            except Exception as exc:
                logger.error(f"Spec document load failed: session_id={session_id} error={type(exc).__name__}: {exc}")
                raise HTTPException(status_code=502, detail="Firestore unavailable.") from exc
            _documents[session_id] = document
            while len(_documents) > _MAX_DOCUMENTS:
                _documents.popitem(last=False)
    return document


async def _respond(document: DocumentActor, handled: bool, events: list[str], wait: bool) -> SpecResponse:
    if wait:
        # Waits for the current section's generation/validation/commit (generation has its own timeout).
        await document.current.settle()
    snapshot: DocumentSnapshot = document.snapshot()
    return SpecResponse(handled=handled, events=events, snapshot=dict(snapshot))


@router.get("/{session_id}", response_model=SpecResponse)
async def get_spec(session_id: str) -> SpecResponse:
    document = await _get_document(session_id)
    return await _respond(document, True, [], wait=False)


@router.post("/{session_id}/events", response_model=SpecResponse)
async def post_spec_event(session_id: str, body: SpecEventBody) -> SpecResponse:
    document = await _get_document(session_id)
    event = _document_event(body)
    handled = document.send(event)
    return await _respond(document, handled, [body.type], body.wait)


@router.post("/{session_id}/utterance", response_model=SpecResponse)
async def post_spec_utterance(session_id: str, body: UtteranceBody) -> SpecResponse:
    """Map a chat/voice utterance to typed events for the current section, then apply them."""
    document = await _get_document(session_id)
    current = document.current
    events = await resolve_utterance(
        body.text,
        state=current.state,
        config=current.config,
        modality=body.modality,
        model_classifier=intent_classifier(session_id),
    )
    handled = bool(events)
    for event in events:
        handled = document.send(ToCurrent(event)) and handled
    return await _respond(document, handled, [type(event).__name__ for event in events], body.wait)
