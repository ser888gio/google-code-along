from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict

from field_schema import FIELD_SCHEMA


class Phase(StrEnum):
    DISCOVERY = "discovery"
    WRAP_UP = "wrap_up"
    READY_TO_FINALIZE = "ready_to_finalize"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"


class FieldStatus(StrEnum):
    MISSING = "missing"
    ANSWERED = "answered"
    DEFERRED = "deferred"
    CLARIFICATION_REQUESTED = "clarification_requested"
    NOT_APPLICABLE = "not_applicable"


class WorkflowEvent(StrEnum):
    FIELDS_EXHAUSTED = "fields_exhausted"
    FIELD_FOUND = "field_found"
    FINISH_REQUESTED = "finish_requested"
    FINALIZE_CHOSEN = "finalize_chosen"
    REOPEN_DEFERRED = "reopen_deferred"
    FINALIZE_STARTED = "finalize_started"
    FINALIZE_COMPLETE = "finalize_complete"
    FINALIZE_FAILED = "finalize_failed"
    FINALIZE_RETRY = "finalize_retry"


class InvalidTransition(Exception):
    pass


class AgentContext(TypedDict):
    phase: str
    active_field: str | None
    clarification_requested: bool
    miss_count: int
    answered_fields: dict[str, str]
    deferred_fields: list[str]
    ready_to_finalize: bool
    finish_requested: bool
    retrying_after_failure: bool
    active_field_coverage_gaps: list[str]
    previous_field_coverage_gaps: list[str]


_TRANSITIONS: dict[tuple[Phase, WorkflowEvent], Phase] = {
    (Phase.DISCOVERY, WorkflowEvent.FIELD_FOUND): Phase.DISCOVERY,
    (Phase.DISCOVERY, WorkflowEvent.FIELDS_EXHAUSTED): Phase.WRAP_UP,
    (Phase.DISCOVERY, WorkflowEvent.FINISH_REQUESTED): Phase.WRAP_UP,
    (Phase.WRAP_UP, WorkflowEvent.FINALIZE_CHOSEN): Phase.READY_TO_FINALIZE,
    (Phase.WRAP_UP, WorkflowEvent.REOPEN_DEFERRED): Phase.DISCOVERY,
    (Phase.WRAP_UP, WorkflowEvent.FIELD_FOUND): Phase.DISCOVERY,
    (Phase.WRAP_UP, WorkflowEvent.FIELDS_EXHAUSTED): Phase.WRAP_UP,
    (Phase.READY_TO_FINALIZE, WorkflowEvent.FINALIZE_STARTED): Phase.FINALIZING,
    (Phase.FINALIZING, WorkflowEvent.FINALIZE_COMPLETE): Phase.COMPLETE,
    (Phase.FINALIZING, WorkflowEvent.FINALIZE_FAILED): Phase.FAILED,
    (Phase.FAILED, WorkflowEvent.FINALIZE_RETRY): Phase.WRAP_UP,
}


@dataclass
class WorkflowState:
    phase: Phase = Phase.DISCOVERY
    active_field: str | None = None
    field_status: dict[str, FieldStatus] = field(default_factory=dict)
    clarification_counts: dict[str, int] = field(default_factory=dict)
    miss_counts: dict[str, int] = field(default_factory=dict)
    last_question_by_field: dict[str, str] = field(default_factory=dict)
    coverage_gaps: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in FIELD_SCHEMA:
            self.field_status.setdefault(key, FieldStatus.MISSING)

    def transition(self, event: WorkflowEvent, **payload) -> None:
        """Advance phase via the FSM table; raises InvalidTransition on bad moves."""
        key = (self.phase, event)
        if key not in _TRANSITIONS:
            raise InvalidTransition(f"Event {event!r} is not valid from phase {self.phase!r}")
        self.phase = _TRANSITIONS[key]

        if event == WorkflowEvent.FIELD_FOUND:
            self.active_field = payload.get("active_field")
        elif event in (
            WorkflowEvent.FINALIZE_CHOSEN,
            WorkflowEvent.FIELDS_EXHAUSTED,
            WorkflowEvent.FINISH_REQUESTED,
            WorkflowEvent.FINALIZE_RETRY,
        ):
            self.active_field = None
        elif event == WorkflowEvent.REOPEN_DEFERRED:
            self.active_field = payload.get("active_field")
            if self.active_field:
                self.field_status[self.active_field] = FieldStatus.MISSING
                self.miss_counts[self.active_field] = 0

    def to_agent_context(
        self,
        *,
        classification_result: str,
        answered_values: dict[str, str],
        deferred_field_keys: list[str],
        previous_active: str | None,
        finish_requested: bool = False,
        retrying_after_failure: bool = False,
    ) -> AgentContext:
        active = self.active_field
        coverage = self.coverage_gaps
        return AgentContext(
            phase=str(self.phase),
            active_field=active,
            clarification_requested=classification_result == "clarification_requested",
            miss_count=self.miss_counts.get(active, 0) if active else 0,
            answered_fields=answered_values,
            deferred_fields=deferred_field_keys,
            ready_to_finalize=self.phase == Phase.READY_TO_FINALIZE,
            finish_requested=finish_requested,
            retrying_after_failure=retrying_after_failure,
            active_field_coverage_gaps=list(coverage.get(active, [])) if active else [],
            previous_field_coverage_gaps=list(coverage.get(previous_active) or []) if previous_active else [],
        )

    def to_dict(self) -> dict:
        return {
            "phase": str(self.phase),
            "active_field": self.active_field,
            "field_status": {k: str(v) for k, v in self.field_status.items()},
            "clarification_counts": dict(self.clarification_counts),
            "miss_counts": dict(self.miss_counts),
            "last_question_by_field": dict(self.last_question_by_field),
            "coverage_gaps": {k: list(v) for k, v in self.coverage_gaps.items()},
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> WorkflowState:
        """Deserialize from a Firestore dict; unknown values fall back to safe defaults."""
        if not isinstance(d, dict):
            return cls()

        raw_phase = d.get("phase", "")
        try:
            phase = Phase(raw_phase)
        except ValueError:
            phase = Phase.DISCOVERY

        active_field = d.get("active_field")
        if active_field not in FIELD_SCHEMA:
            active_field = None

        raw_statuses: dict = d.get("field_status") or {}
        field_status: dict[str, FieldStatus] = {}
        for key in FIELD_SCHEMA:
            raw = raw_statuses.get(key, "")
            try:
                field_status[key] = FieldStatus(raw)
            except ValueError:
                field_status[key] = FieldStatus.MISSING

        def _safe_dict(value) -> dict:
            return value if isinstance(value, dict) else {}

        coverage_raw = _safe_dict(d.get("coverage_gaps"))
        coverage_gaps = {k: list(v) for k, v in coverage_raw.items() if isinstance(v, list)}

        return cls(
            phase=phase,
            active_field=active_field,
            field_status=field_status,
            clarification_counts=_safe_dict(d.get("clarification_counts")),
            miss_counts=_safe_dict(d.get("miss_counts")),
            last_question_by_field=_safe_dict(d.get("last_question_by_field")),
            coverage_gaps=coverage_gaps,
        )
