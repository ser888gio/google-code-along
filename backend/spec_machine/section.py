"""Per-field section lifecycle state machine.

Transitions are synchronous and deterministic. Every side effect (LLM, validation, directory lookup,
Firestore) is an injected async service started on state entry; its result comes back as an internal
completion that is ignored if the state was exited meanwhile. The LLM never chooses a transition.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, TypedDict, TypeVar

from logger import get_logger

from spec_machine.model import (
    BUSY_STATES,
    OPEN_STATES,
    RESOLVED_STATES,
    Accept,
    AgentProposal,
    Cancel,
    CommitKind,
    CommitRequest,
    Confirm,
    Discard,
    DontKnow,
    Edit,
    EventKind,
    GenerateMode,
    GenerateOutput,
    GenerateRequest,
    HelpMe,
    MachineServices,
    MarkStale,
    MarkTbd,
    MetaRequest,
    Modality,
    PersistedSection,
    PersistedStatus,
    ProposalOutput,
    QuestionOutput,
    Regenerate,
    Reject,
    Resume,
    Retry,
    Revise,
    RevisionConflict,
    SectionConfig,
    SectionEvent,
    SectionEventRecord,
    SectionState,
    SectionValidationError,
    Skip,
    Submit,
    SubmitEdit,
    TbdInfo,
    UserMessage,
    WriteMyself,
    make_tbd,
)

logger = get_logger(__name__)

S = SectionState
T = TypeVar("T")

MessageCode = Literal[
    "generation_question",
    "generation_failed",
    "dont_know_offer",
    "dont_know_recommend_tbd",
    "lookup_results",
    "lookup_empty",
    "lookup_failed",
    "validation_error",
    "confirm_value",
    "commit_failed",
    "commit_conflict",
]

DONT_KNOW_TBD_THRESHOLD = 2


@dataclass
class SectionContext:
    status: PersistedStatus
    value: str | None
    tbd: TbdInfo | None
    proposal: str | None
    draft: str | None
    revision: int
    stale: bool
    rationale: str | None = None
    user_input: str | None = None
    feedback: list[str] = field(default_factory=list)
    mode: GenerateMode = "normal"
    modality: Modality = "chat"
    agent_message: str | None = None
    message_code: MessageCode | None = None
    error: str | None = None
    candidate: str | None = None
    candidate_from_proposal: bool = False
    commit_kind: CommitKind = "value"
    pending_tbd: TbdInfo | None = None
    needs_confirmation: bool = False
    dont_know_count: int = 0
    lookup_results: list[str] = field(default_factory=list)

    @classmethod
    def from_persisted(cls, persisted: PersistedSection) -> SectionContext:
        return cls(
            status=persisted["status"],
            value=persisted["value"],
            tbd=persisted["tbd"],
            proposal=persisted["proposal"],
            draft=persisted["draft"],
            revision=persisted["revision"],
            stale=persisted["stale"],
        )


class SectionSnapshot(TypedDict):
    id: str
    label: str
    kind: str
    required: bool
    queued_proposal: str | None
    state: str
    busy: bool
    resolved: bool
    open: bool
    status: PersistedStatus
    value: str | None
    tbd: TbdInfo | None
    proposal: str | None
    rationale: str | None
    draft: str | None
    stale: bool
    revision: int
    agent_message: str | None
    message_code: MessageCode | None
    error: str | None
    candidate: str | None
    needs_confirmation: bool
    lookup_results: list[str]
    dont_know_count: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SectionActor:
    def __init__(
        self,
        config: SectionConfig,
        persisted: PersistedSection,
        services: MachineServices,
        *,
        dependents: tuple[str, ...] = (),
        on_committed: Callable[[str], None] | None = None,
        other_values: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self.config = config
        self.services = services
        self.dependents = dependents
        self.ctx = SectionContext.from_persisted(persisted)
        self.state: SectionState = S.GATHERING
        self._on_committed = on_committed
        self._other_values: Callable[[], Mapping[str, str]] = other_values or dict
        self._token = 0
        self._task: asyncio.Task[None] | None = None
        self._abort: asyncio.Event | None = None
        self._background: set[asyncio.Task[None]] = set()
        self._stopped = False
        self._route_init()

    # --- public API ---

    @property
    def is_ai(self) -> bool:
        return self.config.kind == "ai"

    @property
    def busy(self) -> bool:
        return self.state in BUSY_STATES

    @property
    def resolved(self) -> bool:
        return self.state in RESOLVED_STATES

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES

    @property
    def has_pending(self) -> bool:
        return any(t is not None and not t.done() for t in (self._task, *self._background))

    def can_accept_proposal(self) -> bool:
        return self.is_ai and self.state in (S.ACCEPTED, S.TBD, S.SKIPPED)

    def send(self, event: SectionEvent) -> bool:
        """Apply one event. Returns False when the current state ignores it."""
        if self._stopped:
            return False
        if isinstance(event, MarkStale):
            self.ctx.stale = True
            return True
        return self._handlers[self.state](self, event)

    async def settle(self) -> None:
        """Wait until no invocation or background write is running; re-raises handler bugs."""
        while True:
            pending = [t for t in (self._task, *self._background) if t is not None and not t.done()]
            if not pending:
                return
            done, _ = await asyncio.wait(pending)
            for task in done:
                if not task.cancelled() and (exc := task.exception()) is not None:
                    raise exc

    def stop(self) -> None:
        self._stopped = True
        self._cancel_invocation()

    def snapshot(self, *, queued_proposal: str | None = None) -> SectionSnapshot:
        c = self.ctx
        return {
            "id": self.config.id,
            "label": self.config.label,
            "kind": self.config.kind,
            "required": self.config.required,
            "queued_proposal": queued_proposal,
            "state": str(self.state),
            "busy": self.busy,
            "resolved": self.resolved,
            "open": self.open,
            "status": c.status,
            "value": c.value,
            "tbd": c.tbd,
            "proposal": c.proposal,
            "rationale": c.rationale,
            "draft": c.draft,
            "stale": c.stale,
            "revision": c.revision,
            "agent_message": c.agent_message,
            "message_code": c.message_code,
            "error": c.error,
            "candidate": c.candidate,
            "needs_confirmation": c.needs_confirmation,
            "lookup_results": list(c.lookup_results),
            "dont_know_count": c.dont_know_count,
        }

    # --- transient routing states (never persisted, never observable) ---

    def _has_decision(self) -> bool:
        return self.ctx.status in ("filled", "tbd")

    def _route_init(self) -> None:
        if self.ctx.status == "skipped":
            self._enter(S.SKIPPED)
        else:
            self._route_rest()

    def _route_rest(self) -> None:
        if self.ctx.status == "filled" and self.ctx.value is not None:
            self._enter(S.ACCEPTED)
        elif self.ctx.status == "tbd":
            self._enter(S.TBD)
        elif not self.is_ai:
            self._enter(S.AWAITING_INPUT)
        else:
            self._enter(S.GATHERING)

    def _route_resume(self) -> None:
        if self.is_ai and self.ctx.proposal:
            self._enter(S.PROPOSED)
        elif self.is_ai and self.ctx.draft:
            self._enter(S.EDITING)
        elif not self.is_ai:
            self._enter(S.AWAITING_INPUT)
        else:
            self._enter(S.GATHERING)

    def _route_skipping(self) -> None:
        c = self.ctx
        if self._has_decision():
            self._clear_work_in_progress()
            self._route_rest()
            return
        c.status = "skipped"
        request = MetaRequest(
            section_id=self.config.id,
            expected_revision=c.revision,
            proposal=c.proposal,
            draft=c.draft,
            event=self._record("skip", before=c.value, after=None, reason=None),
        )
        self._enter(S.SKIPPED)
        self._spawn_background(lambda: self.services.persist_meta(request), "persist_meta")

    # --- entry actions ---

    def _enter(self, state: SectionState) -> None:
        self._cancel_invocation()
        self.state = state
        c = self.ctx
        if state is S.GENERATING:
            c.error = None
            self._set_message(None, None)
            generate_request = GenerateRequest(
                config=self.config,
                mode=c.mode,
                value=c.value,
                proposal=c.proposal,
                draft=c.draft,
                user_input=c.user_input,
                feedback=tuple(c.feedback),
                other_values=dict(self._other_values()),
            )
            self._invoke(
                lambda abort: self._generate(generate_request, abort),
                self._on_generated,
                self._on_generate_failed,
            )
        elif state is S.VALIDATING:
            c.error = None
            candidate = c.candidate or ""
            self._invoke(
                lambda _abort: self.services.validate(self.config, candidate),
                self._on_validated,
                self._on_validation_failed,
            )
        elif state is S.COMMITTING:
            c.error = None
            self._set_message(None, None)
            commit_request = self._commit_request()
            self._invoke(
                lambda _abort: self.services.persist(commit_request),
                lambda revision: self._on_committed_ok(commit_request, revision),
                self._on_commit_failed,
            )
        elif state is S.LOOKING_UP:
            c.error = None
            query = c.candidate
            self._invoke(
                lambda _abort: self.services.lookup(self.config, query),
                self._on_looked_up,
                self._on_lookup_failed,
            )
        elif state is S.UNSURE:
            c.dont_know_count += 1
            self._set_unsure_message()
        elif state is S.CONFIRMING:
            self._set_message("confirm_value", f'I understood "{c.candidate}". Is that correct?')

    def _set_message(self, code: MessageCode | None, text: str | None) -> None:
        self.ctx.message_code = code
        self.ctx.agent_message = text

    def _set_unsure_message(self) -> None:
        if self.ctx.dont_know_count >= DONT_KNOW_TBD_THRESHOLD:
            self._set_message(
                "dont_know_recommend_tbd",
                "This one is hard to pin down right now. I suggest marking it as an open item (TBD) "
                "with a short note and who could answer it, or we can skip it for now.",
            )
            return
        help_offer = "work it out together" if self.is_ai else "look it up in the directory"
        self._set_message(
            "dont_know_offer",
            f"No problem. I can help you {help_offer}, mark it as an open item (TBD), or we can skip it for now.",
        )

    # --- state handlers (return False = event ignored in this state) ---

    def _on_gathering(self, event: SectionEvent) -> bool:
        match event:
            case UserMessage(text=text, modality=modality):
                self._start_generation(text, modality, "normal")
            case WriteMyself():
                self.ctx.draft = self.ctx.draft or self.ctx.value
                self._enter(S.EDITING)
            case DontKnow():
                self._enter(S.UNSURE)
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case Cancel() if self._has_decision():
                self._route_rest()
            case _:
                return False
        return True

    def _on_generating(self, event: SectionEvent) -> bool:
        match event:
            case Cancel():
                self._route_rest()
            case Skip():
                self._route_skipping()
            case _:
                return False
        return True

    def _on_generation_failed(self, event: SectionEvent) -> bool:
        match event:
            case Retry():
                self._enter(S.GENERATING)
            case WriteMyself():
                self.ctx.draft = self.ctx.draft or self.ctx.proposal or self.ctx.value
                self._enter(S.EDITING)
            case Cancel():
                self._route_rest()
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case _:
                return False
        return True

    def _on_proposed(self, event: SectionEvent) -> bool:
        c = self.ctx
        match event:
            case Accept():
                self._begin_validation(c.proposal or "", from_proposal=True, needs_confirmation=False)
            case Edit():
                c.draft = c.proposal
                self._enter(S.EDITING)
            case Regenerate(reason=reason):
                self._add_feedback(reason)
                self._enter(S.GENERATING)
            case UserMessage(text=text, modality=modality):
                self._start_generation(text, modality, "normal")
            case Reject(reason=reason):
                self._add_feedback(reason)
                record = self._record("reject", before=c.value, after=c.proposal, reason=reason)
                self._spawn_background(lambda: self.services.record_event(record), "record_event")
                c.proposal = None
                c.rationale = None
                self._route_rest()
            case DontKnow():
                self._enter(S.UNSURE)
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case _:
                return False
        return True

    def _on_editing(self, event: SectionEvent) -> bool:
        c = self.ctx
        match event:
            case SubmitEdit(value=value):
                c.draft = value
                self._begin_validation(value, from_proposal=False, needs_confirmation=False)
            case Cancel():
                c.draft = None
                c.error = None
                if c.proposal:
                    self._enter(S.PROPOSED)
                else:
                    self._route_rest()
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case _:
                return False
        return True

    def _on_awaiting_input(self, event: SectionEvent) -> bool:
        match event:
            case Submit():
                self._submit_simple(event)
            case DontKnow():
                self._enter(S.UNSURE)
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case Cancel() if self._has_decision():
                self._route_rest()
            case _:
                return False
        return True

    def _on_unsure(self, event: SectionEvent) -> bool:
        match event:
            case HelpMe() if self.is_ai:
                self._start_generation(None, self.ctx.modality, "guide")
            case HelpMe():
                self._enter(S.LOOKING_UP)
            case MarkTbd():
                self._start_tbd(event)
            case Skip():
                self._route_skipping()
            case UserMessage(text=text, modality=modality) if self.is_ai:
                self._start_generation(text, modality, "normal")
            case Submit() if not self.is_ai:
                self._submit_simple(event)
            case Cancel():
                self._route_rest()
            case _:
                return False
        return True

    def _on_looking_up(self, event: SectionEvent) -> bool:
        match event:
            case Skip():
                self._route_skipping()
            case Cancel():
                self._route_rest()
            case _:
                return False
        return True

    def _on_busy(self, event: SectionEvent) -> bool:
        return False

    def _on_confirming(self, event: SectionEvent) -> bool:
        c = self.ctx
        match event:
            case Confirm():
                self._enter(S.COMMITTING)
            case Reject():
                c.candidate = None
                c.needs_confirmation = False
                self._set_message(None, None)
                self._enter(S.AWAITING_INPUT)
            case Submit():
                self._submit_simple(event)
            case Skip():
                self._route_skipping()
            case _:
                return False
        return True

    def _on_commit_failed_state(self, event: SectionEvent) -> bool:
        c = self.ctx
        match event:
            case Retry():
                self._enter(S.COMMITTING)
            case Discard():
                c.candidate = None
                c.pending_tbd = None
                c.needs_confirmation = False
                c.error = None
                self._set_message(None, None)
                self._route_rest()
            case _:
                return False
        return True

    def _on_accepted(self, event: SectionEvent) -> bool:
        c = self.ctx
        match event:
            case Edit() if self.is_ai:
                c.draft = c.value
                self._enter(S.EDITING)
            case Edit():
                self._enter(S.AWAITING_INPUT)
            case Revise(instruction=instruction) if self.is_ai:
                self._start_generation(instruction, c.modality, "normal")
            case UserMessage(text=text, modality=modality) if self.is_ai:
                self._start_generation(text, modality, "normal")
            case Submit() if not self.is_ai:
                self._submit_simple(event)
            case AgentProposal() if self.is_ai:
                self._receive_proposal(event)
            case DontKnow():
                self._enter(S.UNSURE)
            case _:
                return False
        return True

    def _on_tbd(self, event: SectionEvent) -> bool:
        match event:
            case Resume() if self.is_ai:
                self._enter(S.GATHERING)
            case Resume():
                self._enter(S.AWAITING_INPUT)
            case UserMessage(text=text, modality=modality) if self.is_ai:
                self._start_generation(text, modality, "normal")
            case Submit() if not self.is_ai:
                self._submit_simple(event)
            case AgentProposal() if self.is_ai:
                self._receive_proposal(event)
            case _:
                return False
        return True

    def _on_skipped(self, event: SectionEvent) -> bool:
        match event:
            case Resume():
                self._route_resume()
            case AgentProposal() if self.is_ai:
                self._receive_proposal(event)
            case _:
                return False
        return True

    _handlers: dict[SectionState, Callable[[SectionActor, SectionEvent], bool]] = {
        S.GATHERING: _on_gathering,
        S.GENERATING: _on_generating,
        S.GENERATION_FAILED: _on_generation_failed,
        S.PROPOSED: _on_proposed,
        S.EDITING: _on_editing,
        S.AWAITING_INPUT: _on_awaiting_input,
        S.LOOKING_UP: _on_looking_up,
        S.CONFIRMING: _on_confirming,
        S.UNSURE: _on_unsure,
        S.VALIDATING: _on_busy,
        S.COMMITTING: _on_busy,
        S.COMMIT_FAILED: _on_commit_failed_state,
        S.ACCEPTED: _on_accepted,
        S.TBD: _on_tbd,
        S.SKIPPED: _on_skipped,
    }

    # --- transition helpers ---

    def _add_feedback(self, reason: str | None) -> None:
        if reason and reason.strip():
            self.ctx.feedback.append(reason.strip())

    def _start_generation(self, user_input: str | None, modality: Modality, mode: GenerateMode) -> None:
        if user_input is not None:
            self.ctx.user_input = user_input
        self.ctx.modality = modality
        self.ctx.mode = mode
        self._enter(S.GENERATING)

    def _receive_proposal(self, event: AgentProposal) -> None:
        self.ctx.proposal = event.proposal
        self.ctx.rationale = event.rationale
        self._enter(S.PROPOSED)

    def _begin_validation(self, candidate: str, *, from_proposal: bool, needs_confirmation: bool) -> None:
        c = self.ctx
        c.candidate = candidate
        c.candidate_from_proposal = from_proposal
        c.commit_kind = "value"
        c.needs_confirmation = needs_confirmation
        self._enter(S.VALIDATING)

    def _submit_simple(self, event: Submit) -> None:
        self.ctx.modality = event.modality
        self._begin_validation(
            event.value,
            from_proposal=False,
            # Speech-to-text often mangles names, so voice input is always read back.
            needs_confirmation=event.modality == "voice" or event.low_confidence,
        )

    def _start_tbd(self, event: MarkTbd) -> None:
        self.ctx.commit_kind = "tbd"
        self.ctx.pending_tbd = make_tbd(event.note, event.open_question, event.owner)
        self._enter(S.COMMITTING)

    def _clear_work_in_progress(self) -> None:
        c = self.ctx
        c.proposal = None
        c.rationale = None
        c.draft = None
        c.user_input = None
        c.feedback = []
        c.mode = "normal"
        c.error = None
        c.candidate = None
        c.candidate_from_proposal = False
        c.commit_kind = "value"
        c.pending_tbd = None
        c.needs_confirmation = False
        c.dont_know_count = 0
        c.lookup_results = []
        self._set_message(None, None)

    def _record(
        self, kind: EventKind, *, before: str | None, after: str | None, reason: str | None
    ) -> SectionEventRecord:
        return {
            "field_key": self.config.id,
            "kind": kind,
            "before": before,
            "after": after,
            "reason": reason,
            "modality": self.ctx.modality,
            "ts": _now_iso(),
        }

    def _commit_request(self) -> CommitRequest:
        c = self.ctx
        if c.commit_kind == "tbd":
            tbd = c.pending_tbd or {}
            return CommitRequest(
                section_id=self.config.id,
                expected_revision=c.revision,
                status="tbd",
                value=None,
                tbd=tbd,
                event=self._record("tbd", before=c.value, after=None, reason=tbd.get("note")),
                dependents=self.dependents,
            )
        kind: EventKind = "accept" if c.candidate_from_proposal else "edit"
        return CommitRequest(
            section_id=self.config.id,
            expected_revision=c.revision,
            status="filled",
            value=c.candidate,
            tbd=None,
            event=self._record(kind, before=c.value, after=c.candidate, reason=None),
            dependents=self.dependents,
        )

    # --- invocation results ---

    async def _generate(self, request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        return await asyncio.wait_for(
            self.services.generate(request, abort),
            timeout=self.services.generation_timeout_s,
        )

    def _on_generated(self, output: GenerateOutput) -> None:
        c = self.ctx
        match output:
            case QuestionOutput(message=message):
                self._set_message("generation_question", message)
                self._enter(S.GATHERING)
            case ProposalOutput(proposal=proposal, rationale=rationale) if proposal.strip():
                c.proposal = proposal.strip()
                c.rationale = rationale
                c.mode = "normal"
                self._enter(S.PROPOSED)
            case _:
                self._on_generate_failed(ValueError("empty proposal"))

    def _on_generate_failed(self, exc: Exception) -> None:
        timed_out = isinstance(exc, TimeoutError)
        if not timed_out:
            logger.warning(f"Section generation failed: section={self.config.id} error={type(exc).__name__}: {exc}")
        self.ctx.error = "timeout" if timed_out else "generation_error"
        self._set_message(
            "generation_failed",
            "I could not prepare a proposal just now. You can retry, write it yourself, or skip it for now.",
        )
        self._enter(S.GENERATION_FAILED)

    def _on_validated(self, value: str) -> None:
        self.ctx.candidate = value
        self._enter(S.CONFIRMING if self.ctx.needs_confirmation else S.COMMITTING)

    def _on_validation_failed(self, exc: Exception) -> None:
        c = self.ctx
        if isinstance(exc, SectionValidationError):
            message = str(exc)
        else:
            logger.warning(f"Section validation errored: section={self.config.id} error={type(exc).__name__}")
            message = "That value could not be checked. Please try again."
        c.error = message
        self._set_message("validation_error", message)
        if self.is_ai:
            c.draft = c.candidate
            self._enter(S.EDITING)
        else:
            self._enter(S.AWAITING_INPUT)

    def _on_looked_up(self, results: list[str]) -> None:
        self.ctx.lookup_results = list(results)
        if results:
            self._set_message("lookup_results", "I found these possible matches: " + ", ".join(results) + ".")
        else:
            self._set_message(
                "lookup_empty",
                "I could not find a match. You can type it in, mark it as an open item (TBD), or skip it for now.",
            )
        self._enter(S.AWAITING_INPUT)

    def _on_lookup_failed(self, exc: Exception) -> None:
        logger.warning(f"Section lookup failed: section={self.config.id} error={type(exc).__name__}")
        self.ctx.error = "lookup_failed"
        self._set_message("lookup_failed", "The lookup is not available right now. You can type the value in.")
        self._enter(S.AWAITING_INPUT)

    def _on_committed_ok(self, request: CommitRequest, revision: int) -> None:
        c = self.ctx
        c.status = request.status
        c.value = request.value
        c.tbd = request.tbd
        c.revision = revision
        c.stale = False
        self._clear_work_in_progress()
        self._route_rest()
        if self._on_committed is not None:
            self._on_committed(self.config.id)

    def _on_commit_failed(self, exc: Exception) -> None:
        conflict = isinstance(exc, RevisionConflict)
        if not conflict:
            logger.warning(f"Section commit failed: section={self.config.id} error={type(exc).__name__}: {exc}")
        self.ctx.error = "conflict" if conflict else "commit_failed"
        self._set_message(
            "commit_conflict" if conflict else "commit_failed",
            "This field was changed elsewhere. Reload it to see the latest value."
            if conflict
            else "Saving failed. You can retry or discard the change.",
        )
        self._enter(S.COMMIT_FAILED)

    # --- invocation plumbing ---

    def _invoke(
        self,
        make: Callable[[asyncio.Event], Awaitable[T]],
        on_done: Callable[[T], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self._token += 1
        token = self._token
        abort = asyncio.Event()
        self._abort = abort

        async def run() -> None:
            try:
                result = await make(abort)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — every service failure maps to an error state
                if self._claim(token):
                    on_error(exc)
                return
            if self._claim(token):
                on_done(result)

        self._task = asyncio.get_running_loop().create_task(run())

    def _claim(self, token: int) -> bool:
        if self._stopped or token != self._token:
            return False
        self._task = None
        self._abort = None
        return True

    def _cancel_invocation(self) -> None:
        task, abort = self._task, self._abort
        self._task = None
        self._abort = None
        self._token += 1
        if abort is not None:
            abort.set()
        if task is not None and not task.done():
            task.cancel()

    def _spawn_background(self, make: Callable[[], Awaitable[None]], label: str) -> None:
        delays = self.services.meta_retry_delays_s
        section_id = self.config.id

        async def run() -> None:
            for attempt in range(len(delays) + 1):
                try:
                    await make()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — fire-and-forget writes never block the user
                    if attempt >= len(delays):
                        logger.warning(f"{label} gave up: section={section_id} error={type(exc).__name__}: {exc}")
                        return
                    await asyncio.sleep(delays[attempt])

        task = asyncio.get_running_loop().create_task(run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
