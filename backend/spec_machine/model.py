"""Typed configuration, events, persisted shapes and injected services for the section state machine."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, NotRequired, TypedDict, cast

from field_schema import FIELD_SCHEMA, InputFormat, SectionKind

PersistedStatus = Literal["empty", "skipped", "tbd", "filled"]
Modality = Literal["chat", "voice"]
EventKind = Literal["accept", "reject", "edit", "tbd", "skip"]
GenerateMode = Literal["normal", "guide"]
CommitKind = Literal["value", "tbd"]

_PERSISTED_STATUSES: frozenset[str] = frozenset({"empty", "skipped", "tbd", "filled"})


@dataclass(frozen=True)
class SectionConfig:
    id: str
    kind: SectionKind
    required: bool
    depends_on: tuple[str, ...] = ()
    label: str = ""
    input_format: InputFormat = "text"


def section_configs_from_schema() -> list[SectionConfig]:
    """Build section configs, in schema order, from `field_schema.FIELD_SCHEMA`."""
    return [
        SectionConfig(
            id=key,
            kind=field_def.get("kind", "ai"),
            required=field_def["required"],
            depends_on=tuple(field_def.get("depends_on", [])),
            label=field_def["label"],
            input_format=field_def.get("input_format", "text"),
        )
        for key, field_def in FIELD_SCHEMA.items()
    ]


def build_dependents(configs: Sequence[SectionConfig]) -> dict[str, tuple[str, ...]]:
    """Invert `depends_on`: for each section, the sections that go stale when it is committed."""
    ids = {c.id for c in configs}
    dependents: dict[str, list[str]] = {c.id: [] for c in configs}
    for config in configs:
        for parent in config.depends_on:
            if parent not in ids:
                raise ValueError(f"Section {config.id!r} depends on unknown section {parent!r}.")
            dependents[parent].append(config.id)
    return {key: tuple(value) for key, value in dependents.items()}


class TbdInfo(TypedDict):
    note: NotRequired[str]
    open_question: NotRequired[str]
    owner: NotRequired[str]


class PersistedSection(TypedDict):
    status: PersistedStatus
    value: str | None
    tbd: TbdInfo | None
    proposal: str | None
    draft: str | None
    revision: int
    stale: bool


def empty_section() -> PersistedSection:
    return {
        "status": "empty",
        "value": None,
        "tbd": None,
        "proposal": None,
        "draft": None,
        "revision": 0,
        "stale": False,
    }


def _opt_str(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def coerce_tbd(raw: object) -> TbdInfo | None:
    if not isinstance(raw, Mapping):
        return None
    return make_tbd(_opt_str(raw.get("note")), _opt_str(raw.get("open_question")), _opt_str(raw.get("owner")))


def make_tbd(note: str | None, open_question: str | None, owner: str | None) -> TbdInfo:
    info: TbdInfo = {}
    if note and note.strip():
        info["note"] = note.strip()
    if open_question and open_question.strip():
        info["open_question"] = open_question.strip()
    if owner and owner.strip():
        info["owner"] = owner.strip()
    return info


def coerce_section(raw: Mapping[str, object] | None) -> PersistedSection:
    """Read a stored section defensively; unknown or malformed values fall back to empty defaults."""
    if not raw:
        return empty_section()
    status_raw = raw.get("status")
    status: PersistedStatus = "empty"
    if isinstance(status_raw, str) and status_raw in _PERSISTED_STATUSES:
        status = cast(PersistedStatus, status_raw)
    revision_raw = raw.get("revision")
    revision = revision_raw if isinstance(revision_raw, int) and revision_raw >= 0 else 0
    value = _opt_str(raw.get("value"))
    tbd = coerce_tbd(raw.get("tbd"))
    if status == "filled" and value is None:
        status = "empty"
    if status == "tbd" and tbd is None:
        tbd = {}
    return {
        "status": status,
        "value": value,
        "tbd": tbd if status == "tbd" else None,
        "proposal": _opt_str(raw.get("proposal")),
        "draft": _opt_str(raw.get("draft")),
        "revision": revision,
        "stale": raw.get("stale") is True,
    }


class SectionState(StrEnum):
    GATHERING = "gathering"
    GENERATING = "generating"
    GENERATION_FAILED = "generationFailed"
    PROPOSED = "proposed"
    EDITING = "editing"
    AWAITING_INPUT = "awaitingInput"
    LOOKING_UP = "lookingUp"
    CONFIRMING = "confirming"
    UNSURE = "unsure"
    VALIDATING = "validating"
    COMMITTING = "committing"
    COMMIT_FAILED = "commitFailed"
    ACCEPTED = "accepted"
    TBD = "tbd"
    SKIPPED = "skipped"


BUSY_STATES: frozenset[SectionState] = frozenset(
    {SectionState.VALIDATING, SectionState.COMMITTING, SectionState.COMMIT_FAILED}
)
RESOLVED_STATES: frozenset[SectionState] = frozenset({SectionState.ACCEPTED, SectionState.TBD})
OPEN_STATES: frozenset[SectionState] = frozenset({SectionState.SKIPPED})


# --- Section events (user intents are typed; the LLM never emits these) ---


@dataclass(frozen=True)
class UserMessage:
    text: str
    modality: Modality = "chat"


@dataclass(frozen=True)
class WriteMyself:
    pass


@dataclass(frozen=True)
class DontKnow:
    pass


@dataclass(frozen=True)
class Skip:
    pass


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class Retry:
    pass


@dataclass(frozen=True)
class Accept:
    pass


@dataclass(frozen=True)
class Edit:
    pass


@dataclass(frozen=True)
class Regenerate:
    reason: str | None = None


@dataclass(frozen=True)
class Reject:
    reason: str | None = None


@dataclass(frozen=True)
class SubmitEdit:
    value: str


@dataclass(frozen=True)
class Submit:
    value: str
    modality: Modality = "chat"
    low_confidence: bool = False


@dataclass(frozen=True)
class HelpMe:
    pass


@dataclass(frozen=True)
class MarkTbd:
    note: str | None = None
    open_question: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class Confirm:
    pass


@dataclass(frozen=True)
class Discard:
    pass


@dataclass(frozen=True)
class Revise:
    instruction: str | None = None


@dataclass(frozen=True)
class Resume:
    pass


@dataclass(frozen=True)
class AgentProposal:
    proposal: str
    rationale: str | None = None


@dataclass(frozen=True)
class MarkStale:
    pass


SectionEvent = (
    UserMessage
    | WriteMyself
    | DontKnow
    | Skip
    | Cancel
    | Retry
    | Accept
    | Edit
    | Regenerate
    | Reject
    | SubmitEdit
    | Submit
    | HelpMe
    | MarkTbd
    | Confirm
    | Discard
    | Revise
    | Resume
    | AgentProposal
    | MarkStale
)


# --- Document events ---


@dataclass(frozen=True)
class Next:
    pass


@dataclass(frozen=True)
class Prev:
    pass


@dataclass(frozen=True)
class GoTo:
    section_id: str


@dataclass(frozen=True)
class ToCurrent:
    event: SectionEvent


@dataclass(frozen=True)
class AgentProposalFor:
    section_id: str
    proposal: str
    rationale: str | None = None


@dataclass(frozen=True)
class ReloadSection:
    section_id: str


@dataclass(frozen=True)
class Finalize:
    pass


@dataclass(frozen=True)
class Reopen:
    pass


DocumentEvent = Next | Prev | GoTo | ToCurrent | AgentProposalFor | ReloadSection | Finalize | Reopen


# --- LLM structured output ---


@dataclass(frozen=True)
class ProposalOutput:
    proposal: str
    rationale: str | None = None


@dataclass(frozen=True)
class QuestionOutput:
    message: str


GenerateOutput = ProposalOutput | QuestionOutput


@dataclass(frozen=True)
class GenerateRequest:
    config: SectionConfig
    mode: GenerateMode
    value: str | None
    proposal: str | None
    draft: str | None
    user_input: str | None
    feedback: tuple[str, ...]
    other_values: Mapping[str, str]


# --- Persistence requests ---


class SectionEventRecord(TypedDict):
    field_key: str
    kind: EventKind
    before: str | None
    after: str | None
    reason: str | None
    modality: Modality
    ts: str


@dataclass(frozen=True)
class CommitRequest:
    section_id: str
    # None means "whatever is stored now" — only the legacy dual-write path uses it.
    expected_revision: int | None
    # "empty" is only written by the legacy clear endpoint during the dual-write period.
    status: Literal["filled", "tbd", "empty"]
    value: str | None
    tbd: TbdInfo | None
    event: SectionEventRecord
    dependents: tuple[str, ...]


@dataclass(frozen=True)
class MetaRequest:
    section_id: str
    expected_revision: int
    proposal: str | None
    draft: str | None
    event: SectionEventRecord


class RevisionConflict(Exception):
    """The stored revision no longer matches what this actor last saw."""


class SectionValidationError(Exception):
    """User-facing validation failure; the message is shown to the user."""


@dataclass(frozen=True)
class LoadedDocument:
    sections: Mapping[str, PersistedSection]
    cursor: str | None


@dataclass(frozen=True)
class ReviewRequest:
    changed_section_id: str
    dependent: SectionConfig
    dependent_status: PersistedStatus
    dependent_tbd: TbdInfo | None
    other_values: Mapping[str, str]


@dataclass(frozen=True)
class OpenItem:
    section_id: str
    label: str
    reason: Literal["skipped", "tbd", "stale", "missing"]
    tbd: TbdInfo | None = None


@dataclass(frozen=True)
class ExportRequest:
    values: Mapping[str, str]
    open_items: Sequence[OpenItem]


GenerateFn = Callable[[GenerateRequest, asyncio.Event], Awaitable[GenerateOutput]]
ValidateFn = Callable[[SectionConfig, str], Awaitable[str]]
LookupFn = Callable[[SectionConfig, str | None], Awaitable[list[str]]]
PersistFn = Callable[[CommitRequest], Awaitable[int]]
PersistMetaFn = Callable[[MetaRequest], Awaitable[None]]
RecordEventFn = Callable[[SectionEventRecord], Awaitable[None]]
LoadDocumentFn = Callable[[], Awaitable[LoadedDocument]]
LoadSectionFn = Callable[[str], Awaitable[PersistedSection]]
SaveCursorFn = Callable[[str | None], Awaitable[None]]
ReviewDependentFn = Callable[[ReviewRequest], Awaitable[ProposalOutput | None]]
ExportSpecFn = Callable[[ExportRequest], Awaitable[None]]


@dataclass(frozen=True)
class MachineServices:
    """Every side effect the machines perform. Swap any of them with `.provide(...)` (tests, other backends)."""

    generate: GenerateFn
    validate: ValidateFn
    lookup: LookupFn
    persist: PersistFn
    persist_meta: PersistMetaFn
    record_event: RecordEventFn
    load_document: LoadDocumentFn
    load_section: LoadSectionFn
    save_cursor: SaveCursorFn
    review_dependent: ReviewDependentFn
    export_spec: ExportSpecFn
    generation_timeout_s: float = 45.0
    meta_retry_delays_s: tuple[float, ...] = field(default=(0.5, 2.0, 5.0))

    def provide(
        self,
        *,
        generate: GenerateFn | None = None,
        validate: ValidateFn | None = None,
        lookup: LookupFn | None = None,
        persist: PersistFn | None = None,
        persist_meta: PersistMetaFn | None = None,
        record_event: RecordEventFn | None = None,
        load_document: LoadDocumentFn | None = None,
        load_section: LoadSectionFn | None = None,
        save_cursor: SaveCursorFn | None = None,
        review_dependent: ReviewDependentFn | None = None,
        export_spec: ExportSpecFn | None = None,
        generation_timeout_s: float | None = None,
        meta_retry_delays_s: tuple[float, ...] | None = None,
    ) -> MachineServices:
        return MachineServices(
            generate=generate or self.generate,
            validate=validate or self.validate,
            lookup=lookup or self.lookup,
            persist=persist or self.persist,
            persist_meta=persist_meta or self.persist_meta,
            record_event=record_event or self.record_event,
            load_document=load_document or self.load_document,
            load_section=load_section or self.load_section,
            save_cursor=save_cursor or self.save_cursor,
            review_dependent=review_dependent or self.review_dependent,
            export_spec=export_spec or self.export_spec,
            generation_timeout_s=(
                generation_timeout_s if generation_timeout_s is not None else self.generation_timeout_s
            ),
            meta_retry_delays_s=meta_retry_delays_s if meta_retry_delays_s is not None else self.meta_retry_delays_s,
        )
