"""Utterance -> typed event mapping, deterministic validation, generator output parsing, legacy mirror."""

from __future__ import annotations

from typing import Any, cast

import pytest
from spec_machine import store as store_module
from spec_machine.intents import map_utterance, resolve_utterance
from spec_machine.legacy_mirror import mirror_accepted, mirror_cleared, mirror_dismissed
from spec_machine.model import (
    Accept,
    Cancel,
    Confirm,
    DontKnow,
    MarkTbd,
    ProposalOutput,
    QuestionOutput,
    Regenerate,
    Reject,
    Resume,
    SectionConfig,
    SectionEvent,
    SectionState,
    SectionValidationError,
    Skip,
    Submit,
    UserMessage,
)
from spec_machine.services import parse_generate_output, search_directory, validate_value

from tests.fake_firestore import FakeFirestore, fake_transactional

S = SectionState
OWNER = SectionConfig("product_owner", "simple", True, label="Product Owner", input_format="name")
TITLE = SectionConfig("use_case_title", "ai", True, label="Use Case Title")


def events(text: str, state: SectionState, kind: str = "simple", modality: str = "chat") -> tuple[SectionEvent, ...]:
    return map_utterance(text, state=state, kind=cast(Any, kind), modality=cast(Any, modality)).events


@pytest.mark.parametrize("text", ["skip", "later", "Next", "come back to this", "přeskočit", "později", "Skip it."])
def test_skip_phrases(text: str) -> None:
    assert events(text, S.AWAITING_INPUT) == (Skip(),)


@pytest.mark.parametrize("text", ["I don't know", "I don’t know", "no idea", "not sure", "Nevím", "netuším"])
def test_dont_know_phrases(text: str) -> None:
    assert events(text, S.AWAITING_INPUT) == (DontKnow(),)


def test_explicit_skip_wins_over_dont_know() -> None:
    assert events("I don't know, skip it", S.GATHERING, "ai") == (Skip(),)


def test_unsure_value_is_low_confidence_submit_for_simple_fields() -> None:
    assert events("not sure, maybe Petr Novák", S.AWAITING_INPUT) == (Submit("Petr Novák", low_confidence=True),)


def test_unsure_value_is_a_message_for_ai_fields() -> None:
    assert events("not sure, maybe weekly", S.GATHERING, "ai") == (UserMessage("weekly"),)


@pytest.mark.parametrize(
    ("text", "owner"),
    [
        ("ask Martin", "Martin"),
        ("Martin would know", "Martin"),
        ("You should ask Jana Nováková.", "Jana Nováková"),
        ("zeptej se Petra Nováka", "Petra Nováka"),
    ],
)
def test_naming_someone_who_knows_marks_tbd_with_owner(text: str, owner: str) -> None:
    (event,) = events(text, S.AWAITING_INPUT)
    assert isinstance(event, MarkTbd)
    assert event.owner == owner


def test_who_would_know_is_not_an_owner() -> None:
    assert not any(isinstance(e, MarkTbd) for e in events("who would know?", S.GATHERING, "ai"))


@pytest.mark.parametrize("text", ["yes", "Looks good!", "ano", "vypadá to dobře", "ok, thanks"])
def test_affirmation_in_proposed_accepts(text: str) -> None:
    assert events(text, S.PROPOSED, "ai") == (Accept(),)


@pytest.mark.parametrize("text", ["make it shorter", "add the patent office", "yes but mention the deadline too"])
def test_refinement_in_proposed_is_a_user_message(text: str) -> None:
    assert events(text, S.PROPOSED, "ai") == (UserMessage(text),)


def test_bare_no_in_proposed_rejects_and_another_one_regenerates() -> None:
    assert events("no", S.PROPOSED, "ai") == (Reject(),)
    assert events("another version please", S.PROPOSED, "ai") == (Regenerate(),)


def test_confirming_yes_no_and_correction() -> None:
    assert events("yes", S.CONFIRMING) == (Confirm(),)
    assert events("no", S.CONFIRMING) == (Reject(),)
    assert events("no, it's Jana Nováková", S.CONFIRMING, modality="voice") == (
        Submit("Jana Nováková", modality="voice"),
    )


def test_long_content_with_command_words_is_content() -> None:
    text = "The next step is that the report is approved later by the finance controller each month"
    assert events(text, S.GATHERING, "ai") == (UserMessage(text),)


def test_answering_a_skipped_section_resumes_it_first() -> None:
    assert events("Petr Novák", S.SKIPPED) == (Resume(), Submit("Petr Novák"))


def test_cancel_phrase() -> None:
    assert events("never mind", S.EDITING, "ai") == (Cancel(),)


@pytest.mark.asyncio
async def test_small_model_only_for_ambiguous_simple_replies_and_voice_forces_confirmation() -> None:
    calls: list[str] = []

    async def classifier(text: str, config: SectionConfig) -> SectionEvent | None:
        calls.append(text)
        return Submit("Petr Novák", low_confidence=False)

    clear = await resolve_utterance("Petr Novák", state=S.AWAITING_INPUT, config=OWNER, model_classifier=classifier)
    assert clear == (Submit("Petr Novák"),)
    assert calls == []

    ambiguous = "well the person who signs it off is probably Petr from finance?"
    result = await resolve_utterance(
        ambiguous, state=S.AWAITING_INPUT, config=OWNER, modality="voice", model_classifier=classifier
    )
    assert result == (Submit("Petr Novák", modality="voice", low_confidence=True),)
    assert calls == [ambiguous]

    await resolve_utterance(ambiguous, state=S.GATHERING, config=TITLE, model_classifier=classifier)
    assert len(calls) == 1


# --- deterministic validation & parsing ---


def test_validate_name_canonicalises_against_directory_and_rejects_questions() -> None:
    directory = {"name": ["Petr Novák"]}
    assert validate_value(OWNER, "petr novak.", directory) == "Petr Novák"
    assert validate_value(OWNER, "Someone New", directory) == "Someone New"
    with pytest.raises(SectionValidationError):
        validate_value(OWNER, "who is it?", directory)
    with pytest.raises(SectionValidationError):
        validate_value(OWNER, "   ", directory)


def test_validate_number_requires_a_digit() -> None:
    hours = SectionConfig("saved_time_hours_per_year", "simple", False, input_format="number")
    assert validate_value(hours, "~80 hours/year", {}) == "~80 hours/year"
    with pytest.raises(SectionValidationError):
        validate_value(hours, "a lot", {})


def test_directory_search_ranks_matches_and_lists_entries_without_query() -> None:
    entries = ["Jana Nováková", "Petr Novák", "Martin Dvořák"]
    assert search_directory(entries, "novak")[:2] == ["Jana Nováková", "Petr Novák"]
    assert search_directory(entries, "dvorak") == ["Martin Dvořák"]
    assert search_directory(entries, None, limit=2) == ["Jana Nováková", "Petr Novák"]


def test_parse_generate_output() -> None:
    assert parse_generate_output({"type": "proposal", "proposal": " X ", "rationale": ""}) == ProposalOutput("X")
    assert parse_generate_output({"type": "question", "message": "Who?"}) == QuestionOutput("Who?")
    with pytest.raises(ValueError):
        parse_generate_output({"type": "proposal", "proposal": ""})
    with pytest.raises(ValueError):
        parse_generate_output({"type": "accept"})


def test_schema_marks_name_and_figure_fields_simple() -> None:
    from spec_machine.model import section_configs_from_schema

    kinds = {c.id: c.kind for c in section_configs_from_schema()}
    assert len(kinds) == 28
    assert {k for k, v in kinds.items() if v == "simple"} == {
        "department",
        "requester",
        "product_owner",
        "saved_time_hours_per_year",
        "cost_saving",
        "revenue_increase",
        "comments",
        "attachments",
    }


# --- legacy dual-write mirror ---


def test_legacy_mirror_writes_sections_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module.firestore, "transactional", fake_transactional, raising=False)
    db = FakeFirestore()
    client = cast(Any, db)

    mirror_accepted(client, "s1", {"use_case_title": "Patents reporting", "not_a_field": "x"}, "user_manual")
    mirror_accepted(client, "s1", {"use_case_title": "Patents reporting"}, "user_manual")
    mirror_dismissed(client, "s1", {"department": "Finance"})
    mirror_cleared(client, "s1", ["use_case_title"])

    from config import FIRESTORE_COLLECTION

    section = db.docs[(FIRESTORE_COLLECTION, "s1", "sections", "use_case_title")]
    assert section["status"] == "empty"
    assert section["value"] is None
    assert section["revision"] == 2
    kinds = sorted(d["kind"] for p, d in db.docs.items() if len(p) == 4 and p[2] == "section_events")
    assert kinds == ["edit", "edit", "reject"]
    assert not any(p[-1] == "not_a_field" for p in db.docs)


def test_legacy_mirror_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(fn: Any) -> Any:
        raise RuntimeError("firestore down")

    monkeypatch.setattr(store_module.firestore, "transactional", boom, raising=False)
    mirror_accepted(cast(Any, FakeFirestore()), "s1", {"use_case_title": "X"}, "user_manual")
