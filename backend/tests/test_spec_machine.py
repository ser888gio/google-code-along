"""Scenario tests for the section/document state machines, against the real Firestore store on a fake client."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from spec_machine import store as store_module
from spec_machine.document import DocumentActor, DocumentState
from spec_machine.model import (
    Accept,
    AgentProposalFor,
    Cancel,
    CommitRequest,
    Confirm,
    DontKnow,
    Edit,
    ExportRequest,
    Finalize,
    GenerateOutput,
    GenerateRequest,
    GoTo,
    HelpMe,
    MachineServices,
    MarkTbd,
    MetaRequest,
    Next,
    Prev,
    ProposalOutput,
    QuestionOutput,
    Reject,
    ReloadSection,
    ReviewRequest,
    Revise,
    SectionConfig,
    SectionEvent,
    SectionState,
    Skip,
    Submit,
    SubmitEdit,
    ToCurrent,
    UserMessage,
    WriteMyself,
    empty_section,
)
from spec_machine.services import search_directory, validate_value
from spec_machine.store import FirestoreSectionStore

from tests.fake_firestore import FakeFirestore, fake_transactional

S = SectionState
SESSION = "sess-1"
COLLECTION = "srs_sessions"

CONFIGS = [
    SectionConfig("title", "ai", True, label="Title"),
    SectionConfig("owner", "simple", True, label="Owner", input_format="name"),
    SectionConfig("purpose", "ai", True, depends_on=("title",), label="Purpose"),
    SectionConfig("notes", "ai", False, depends_on=("title",), label="Notes"),
    SectionConfig("budget", "simple", False, label="Budget", input_format="number"),
]
DIRECTORY = {"name": ["Petr Novák", "Jana Nováková", "Martin Dvořák"]}


@pytest.fixture(autouse=True)
def _fake_transactions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.firestore, "transactional", fake_transactional, raising=False)


class ScriptedLLM:
    def __init__(self, *outputs: GenerateOutput | Exception) -> None:
        self.outputs = list(outputs)
        self.requests: list[GenerateRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def __call__(self, request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        self.requests.append(request)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Harness:
    def __init__(self, llm: ScriptedLLM | None = None, *, allow_tbd: bool = False, timeout_s: float = 2.0) -> None:
        self.db = FakeFirestore()
        self.store = FirestoreSectionStore(cast(Any, self.db), SESSION, collection=COLLECTION)
        self.llm = llm or ScriptedLLM()
        self.allow_tbd = allow_tbd
        self.reviews: list[ReviewRequest] = []
        self.review_result: ProposalOutput | None = None
        self.exports: list[ExportRequest] = []

        async def validate(config: SectionConfig, candidate: str) -> str:
            return validate_value(config, candidate, DIRECTORY)

        async def lookup(config: SectionConfig, query: str | None) -> list[str]:
            return search_directory(DIRECTORY.get(config.input_format, []), query)

        async def review(request: ReviewRequest) -> ProposalOutput | None:
            self.reviews.append(request)
            return self.review_result

        async def export(request: ExportRequest) -> None:
            self.exports.append(request)

        async def persist(request: CommitRequest) -> int:
            return self.store.commit(request)

        async def persist_meta(request: Any) -> None:
            self.store.save_meta(request)

        async def record_event(record: Any) -> None:
            self.store.record_event(record)

        async def load_document() -> Any:
            return self.store.load_document()

        async def load_section(section_id: str) -> Any:
            return self.store.load_section(section_id)

        async def save_cursor(cursor: str | None) -> None:
            self.store.save_cursor(cursor)

        self.services = MachineServices(
            generate=self.llm,
            validate=validate,
            lookup=lookup,
            persist=persist,
            persist_meta=persist_meta,
            record_event=record_event,
            load_document=load_document,
            load_section=load_section,
            save_cursor=save_cursor,
            review_dependent=review,
            export_spec=export,
            generation_timeout_s=timeout_s,
            meta_retry_delays_s=(),
        )

    def seed(self, section_id: str, **fields: Any) -> None:
        self.db.docs[(COLLECTION, SESSION, "sections", section_id)] = {**empty_section(), **fields}

    def seed_cursor(self, cursor: str) -> None:
        self.db.docs[(COLLECTION, SESSION)] = {"spec_cursor": cursor}

    def stored(self, section_id: str) -> dict[str, Any]:
        return self.db.docs.get((COLLECTION, SESSION, "sections", section_id), {})

    def event_kinds(self, section_id: str | None = None) -> list[str]:
        events = [
            data
            for path, data in self.db.docs.items()
            if len(path) == 4
            and path[2] == "section_events"
            and (section_id is None or data["field_key"] == section_id)
        ]
        return [e["kind"] for e in sorted(events, key=lambda e: e["ts"])]

    async def load(self) -> DocumentActor:
        return await DocumentActor.load(CONFIGS, self.services, allow_tbd_on_finalize=self.allow_tbd)


async def send(doc: DocumentActor, *events: SectionEvent) -> None:
    for event in events:
        doc.send(ToCurrent(event))
        await doc.settle()


# --- 1 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_reject_reason_reaches_llm_then_accept_persists() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Reporting"), ProposalOutput("Patents reporting")))
    doc = await h.load()
    title = doc.sections["title"]
    assert title.state is S.GATHERING

    await send(doc, UserMessage("we report on patents"))
    assert title.state is S.PROPOSED
    assert title.ctx.proposal == "Reporting"

    await send(doc, Reject("too vague, mention patents"))
    assert title.state is S.GATHERING
    assert title.ctx.proposal is None

    await send(doc, UserMessage("monthly patents overview"))
    assert h.llm.requests[-1].feedback == ("too vague, mention patents",)
    assert title.state is S.PROPOSED

    await send(doc, Accept())
    assert title.state is S.ACCEPTED
    assert title.ctx.value == "Patents reporting"
    stored = h.stored("title")
    assert stored["status"] == "filled"
    assert stored["value"] == "Patents reporting"
    assert stored["revision"] == 1
    assert stored["proposal"] is None
    assert h.event_kinds("title") == ["reject", "accept"]
    assert title.ctx.feedback == []


# --- 2 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_failure_then_cancel() -> None:
    h = Harness(ScriptedLLM(RuntimeError("model down")))
    doc = await h.load()
    title = doc.sections["title"]

    await send(doc, UserMessage("something"))
    assert title.state is S.GENERATION_FAILED
    assert title.ctx.error == "generation_error"
    assert title.ctx.message_code == "generation_failed"

    await send(doc, Cancel())
    assert title.state is S.GATHERING
    assert h.stored("title") == {}


@pytest.mark.asyncio
async def test_generation_timeout_goes_to_generation_failed() -> None:
    async def slow(request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        await asyncio.sleep(10)
        return ProposalOutput("late")

    h = Harness(timeout_s=0.01)
    doc = await DocumentActor.load(CONFIGS, h.services.provide(generate=slow))

    await send(doc, UserMessage("x"))
    assert doc.current.state is S.GENERATION_FAILED
    assert doc.current.ctx.error == "timeout"


@pytest.mark.asyncio
async def test_exiting_generating_aborts_the_llm_call() -> None:
    signals: list[asyncio.Event] = []
    cancelled: list[bool] = []

    async def hang(request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        signals.append(abort)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return ProposalOutput("never")

    h = Harness()
    doc = await DocumentActor.load(CONFIGS, h.services.provide(generate=hang))
    doc.send(ToCurrent(UserMessage("x")))
    await asyncio.sleep(0)
    assert doc.current.state is S.GENERATING and len(signals) == 1

    doc.send(ToCurrent(Cancel()))
    assert signals[0].is_set()
    await asyncio.sleep(0)
    assert cancelled == [True]
    assert doc.current.state is S.GATHERING


# --- 3 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_on_unfinished_section_auto_skips_and_keeps_proposal() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Patents reporting")))
    doc = await h.load()
    await send(doc, UserMessage("patents"))

    assert doc.send(Next())
    await doc.settle()
    title = doc.sections["title"]
    assert title.state is S.SKIPPED
    assert title.ctx.proposal == "Patents reporting"
    assert doc.cursor == "owner"
    stored = h.stored("title")
    assert stored["status"] == "skipped"
    assert stored["proposal"] == "Patents reporting"
    assert stored["revision"] == 0
    assert h.event_kinds("title") == ["skip"]
    assert h.db.docs[(COLLECTION, SESSION)]["spec_cursor"] == "owner"


# --- 4 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_section_dont_know_lookup_voice_submit_confirm_without_llm() -> None:
    h = Harness()
    doc = await h.load()
    doc.send(GoTo("owner"))
    await doc.settle()
    owner = doc.sections["owner"]
    assert owner.state is S.AWAITING_INPUT

    await send(doc, DontKnow())
    assert owner.state is S.UNSURE
    await send(doc, HelpMe())
    assert owner.state is S.AWAITING_INPUT
    assert owner.ctx.lookup_results == DIRECTORY["name"]

    await send(doc, Submit("petr novak", modality="voice"))
    assert owner.state is S.CONFIRMING
    assert owner.ctx.candidate == "Petr Novák"
    assert owner.ctx.message_code == "confirm_value"

    await send(doc, Confirm())
    assert owner.state is S.ACCEPTED
    assert h.stored("owner")["value"] == "Petr Novák"

    assert doc.send(ToCurrent(Revise("make it better"))) is False
    await doc.settle()
    assert owner.state is S.ACCEPTED
    assert h.llm.calls == 0


@pytest.mark.asyncio
async def test_simple_sections_never_call_the_llm() -> None:
    h = Harness()
    doc = await h.load()
    for section_id in ("owner", "budget"):
        doc.send(GoTo(section_id))
        await doc.settle()
        for event in (
            UserMessage("free text"),
            Revise("x"),
            WriteMyself(),
            DontKnow(),
            HelpMe(),
            Submit("not a number"),
            Cancel(),
        ):
            doc.send(ToCurrent(event))
            await doc.settle()
    assert h.llm.calls == 0


# --- 5 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dont_know_then_mark_tbd_is_persisted() -> None:
    h = Harness()
    doc = await h.load()
    title = doc.sections["title"]

    await send(doc, DontKnow())
    assert title.state is S.UNSURE and title.ctx.message_code == "dont_know_offer"
    await send(doc, Cancel(), DontKnow())
    assert title.ctx.dont_know_count == 2
    assert title.ctx.message_code == "dont_know_recommend_tbd"

    await send(doc, MarkTbd(note="needs the patent office", open_question="Which office?", owner="Martin"))
    assert title.state is S.TBD
    stored = h.stored("title")
    assert stored["status"] == "tbd"
    assert stored["tbd"] == {"note": "needs the patent office", "open_question": "Which office?", "owner": "Martin"}
    assert stored["revision"] == 1
    assert h.event_kinds("title") == ["tbd"]
    assert title.ctx.dont_know_count == 0


# --- 6 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_on_last_section_reviews_and_skipped_required_blocks_finalize() -> None:
    h = Harness()
    doc = await h.load()
    for _ in CONFIGS:
        assert doc.send(Next())
    await doc.settle()

    assert doc.state is DocumentState.REVIEWING_OPEN_ITEMS
    reasons = {item.section_id: item.reason for item in doc.open_items}
    assert reasons == {key.id: "skipped" for key in CONFIGS}

    assert doc.send(Finalize()) is False
    assert doc.state is DocumentState.REVIEWING_OPEN_ITEMS
    assert doc.finalize_blocked == ["title", "owner", "purpose"]
    assert h.exports == []


# --- 7 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resuming_skipped_section_shows_same_proposal_then_accept() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Patents reporting")))
    doc = await h.load()
    await send(doc, UserMessage("patents"))
    doc.send(Next())
    doc.send(Prev())
    await doc.settle()

    title = doc.sections["title"]
    assert title.state is S.PROPOSED
    assert title.ctx.proposal == "Patents reporting"
    await send(doc, Accept())
    assert title.state is S.ACCEPTED
    assert h.stored("title")["value"] == "Patents reporting"
    assert h.llm.calls == 1


# --- 8 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_revision_keeps_old_value() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Shorter title")))
    h.seed("title", status="filled", value="Original title", revision=3)
    doc = await h.load()
    title = doc.sections["title"]
    assert title.state is S.ACCEPTED

    await send(doc, Revise("make it shorter"))
    assert title.state is S.PROPOSED
    assert title.ctx.value == "Original title"

    await send(doc, Reject("no, keep the meaning"))
    assert title.state is S.ACCEPTED
    assert title.ctx.value == "Original title"
    assert h.stored("title")["value"] == "Original title"
    assert h.stored("title")["revision"] == 3


# --- 9 ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_proposal_is_queued_and_delivered_on_entry() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Patents reporting")))
    h.seed("notes", status="skipped")
    h.review_result = ProposalOutput("Covers patent filings only", "derived from the title")
    doc = await h.load()

    await send(doc, UserMessage("patents"), Accept())
    assert [r.dependent.id for r in h.reviews] == ["notes"]
    assert doc.cursor == "title"
    assert doc.sections["title"].state is S.ACCEPTED
    assert doc.sections["notes"].state is S.SKIPPED
    assert doc.queued["notes"].proposal == "Covers patent filings only"
    snapshot = doc.snapshot()
    assert snapshot["sections"][3]["queued_proposal"] == "Covers patent filings only"

    doc.send(GoTo("notes"))
    await doc.settle()
    notes = doc.sections["notes"]
    assert notes.state is S.PROPOSED
    assert notes.ctx.proposal == "Covers patent filings only"
    assert "notes" not in doc.queued


@pytest.mark.asyncio
async def test_agent_proposal_for_current_resolved_section_is_delivered_immediately() -> None:
    h = Harness()
    h.seed("title", status="filled", value="Old", revision=1)
    doc = await h.load()
    doc.send(AgentProposalFor("title", "Better title"))
    assert doc.sections["title"].state is S.PROPOSED
    assert doc.queued == {}


# --- 10 --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_marks_dependents_stale_in_memory_and_firestore() -> None:
    h = Harness()
    h.seed("title", status="filled", value="A", revision=1)
    h.seed("purpose", status="filled", value="B", revision=1)
    doc = await h.load()

    await send(doc, Edit(), SubmitEdit("A2"))
    assert doc.sections["title"].state is S.ACCEPTED
    assert doc.sections["purpose"].ctx.stale is True
    assert h.stored("purpose")["stale"] is True
    assert h.stored("purpose")["revision"] == 1
    assert h.stored("title")["stale"] is False
    assert h.event_kinds("title") == ["edit"]

    doc.send(GoTo("budget"))
    doc.send(Next())
    await doc.settle()
    reasons = {item.section_id: item.reason for item in doc.open_items}
    assert reasons["purpose"] == "stale"


# --- 11 --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_succeeds_with_optional_sections_skipped_or_tbd() -> None:
    h = Harness()
    h.seed("title", status="filled", value="Patents reporting", revision=1)
    h.seed("owner", status="filled", value="Petr Novák", revision=1)
    h.seed("purpose", status="filled", value="Monthly overview", revision=1)
    h.seed("notes", status="skipped")
    h.seed("budget", status="tbd", tbd={"owner": "Martin"}, revision=1)
    h.seed_cursor("budget")
    doc = await h.load()

    assert doc.send(Next())
    assert doc.state is DocumentState.REVIEWING_OPEN_ITEMS
    assert doc.send(Finalize())
    await doc.settle()
    assert doc.state is DocumentState.COMPLETED
    assert len(h.exports) == 1
    assert h.exports[0].values == {
        "title": "Patents reporting",
        "owner": "Petr Novák",
        "purpose": "Monthly overview",
    }
    assert [(i.section_id, i.tbd) for i in h.exports[0].open_items] == [("budget", {"owner": "Martin"})]


@pytest.mark.asyncio
async def test_required_tbd_only_finalizes_when_allowed() -> None:
    for allow, expected in ((False, False), (True, True)):
        h = Harness(allow_tbd=allow)
        h.seed("title", status="tbd", tbd={"note": "later"}, revision=1)
        h.seed("owner", status="filled", value="Petr", revision=1)
        h.seed("purpose", status="filled", value="P", revision=1)
        h.seed_cursor("budget")
        doc = await h.load()
        doc.send(Next())
        assert doc.send(Finalize()) is expected
        await doc.settle()


# --- 12 --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rehydration_restores_states_from_persisted_fields_only() -> None:
    h = Harness()
    h.seed("title", status="filled", value="T", revision=2)
    h.seed("owner", status="tbd", tbd={"owner": "Martin"}, revision=1)
    h.seed("purpose", status="skipped", proposal="Kept proposal")
    h.seed("notes", status="bogus", value=None, draft="half-written")
    h.seed_cursor("purpose")
    doc = await h.load()

    states = {key: actor.state for key, actor in doc.sections.items()}
    assert states == {
        "title": S.ACCEPTED,
        "owner": S.TBD,
        "purpose": S.SKIPPED,
        "notes": S.GATHERING,
        "budget": S.AWAITING_INPUT,
    }
    assert doc.cursor == "purpose"
    assert doc.sections["title"].ctx.revision == 2
    assert doc.sections["purpose"].ctx.proposal == "Kept proposal"
    stored_keys = {key for data in h.db.docs.values() for key in data}
    assert "state" not in stored_keys

    doc.send(GoTo("notes"))
    doc.send(GoTo("purpose"))
    await doc.settle()
    assert doc.sections["purpose"].state is S.PROPOSED


# --- 13 --------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revision_conflict_commit_failed_then_reload_section() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("Mine")))
    doc = await h.load()
    await send(doc, UserMessage("x"))

    other_instance = FirestoreSectionStore(cast(Any, h.db), SESSION, collection=COLLECTION)
    other_instance.commit(
        CommitRequest(
            "title",
            0,
            "filled",
            "Theirs",
            None,
            {
                "field_key": "title",
                "kind": "edit",
                "before": None,
                "after": "Theirs",
                "reason": None,
                "modality": "chat",
                "ts": "2026-11-02T00:00:00+00:00",
            },
            (),
        )
    )

    await send(doc, Accept())
    title = doc.sections["title"]
    assert title.state is S.COMMIT_FAILED
    assert title.ctx.error == "conflict"
    assert doc.send(Next()) is False

    assert doc.send(ReloadSection("title"))
    await doc.settle()
    reloaded = doc.sections["title"]
    assert reloaded is not title
    assert reloaded.state is S.ACCEPTED
    assert reloaded.ctx.value == "Theirs"
    assert reloaded.ctx.revision == 1
    assert h.stored("title")["value"] == "Theirs"


# --- extra guarantees ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigation_is_ignored_while_section_is_busy() -> None:
    gate = asyncio.Event()
    h = Harness()

    async def slow_validate(config: SectionConfig, candidate: str) -> str:
        await gate.wait()
        return candidate

    doc = await DocumentActor.load(CONFIGS, h.services.provide(validate=slow_validate))
    doc.send(ToCurrent(WriteMyself()))
    doc.send(ToCurrent(SubmitEdit("My title")))
    assert doc.current.busy
    assert doc.send(Next()) is False
    assert doc.send(GoTo("owner")) is False
    gate.set()
    await doc.settle()
    assert doc.sections["title"].state is S.ACCEPTED


@pytest.mark.asyncio
async def test_question_output_returns_to_gathering_with_agent_message() -> None:
    h = Harness(ScriptedLLM(QuestionOutput("Who uses this report?")))
    doc = await h.load()
    await send(doc, UserMessage("a report"))
    assert doc.current.state is S.GATHERING
    assert doc.current.ctx.agent_message == "Who uses this report?"


@pytest.mark.asyncio
async def test_validation_error_returns_simple_section_to_input() -> None:
    h = Harness()
    h.seed_cursor("budget")
    doc = await h.load()
    await send(doc, Submit("a lot"))
    budget = doc.sections["budget"]
    assert budget.state is S.AWAITING_INPUT
    assert budget.ctx.message_code == "validation_error"
    await send(doc, Submit("~80 hours"))
    assert budget.state is S.ACCEPTED


@pytest.mark.asyncio
async def test_skip_on_filled_section_drops_unfinished_revision() -> None:
    h = Harness(ScriptedLLM(ProposalOutput("New")))
    h.seed("title", status="filled", value="Old", revision=1)
    doc = await h.load()
    await send(doc, Revise(), Skip())
    title = doc.sections["title"]
    assert title.state is S.ACCEPTED
    assert title.ctx.proposal is None
    assert h.stored("title")["status"] == "filled"


def test_skip_is_not_persisted_over_a_newer_decision() -> None:
    h = Harness()
    h.seed("title", status="filled", value="Theirs", revision=2)
    h.store.save_meta(
        MetaRequest(
            "title",
            1,
            "stale proposal",
            None,
            {
                "field_key": "title",
                "kind": "skip",
                "before": None,
                "after": None,
                "reason": None,
                "modality": "chat",
                "ts": "t",
            },
        )
    )
    assert h.stored("title")["status"] == "filled"
    assert h.event_kinds() == []


def test_event_reason_is_redacted_before_persistence() -> None:
    h = Harness()
    h.store.record_event(
        {
            "field_key": "title",
            "kind": "reject",
            "before": None,
            "after": "x",
            "reason": "mail me at jana@example.com",
            "modality": "chat",
            "ts": "t",
        }
    )
    stored = next(data for path, data in h.db.docs.items() if path[2] == "section_events")
    assert "jana@example.com" not in stored["reason"]
