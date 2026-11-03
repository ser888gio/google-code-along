"""Map chat/voice utterances to typed section events before they reach the machine.

Keyword rules (Czech + English, diacritics-insensitive) decide first. Only an ambiguous reply on a
simple field falls back to a small classifier model — never the reasoning agent, never the machine's
`generate` service.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from answer_classifier import clean_direct_answer_value, is_plausible_direct_answer
from field_schema import SectionKind

from spec_machine.model import (
    Accept,
    Cancel,
    Confirm,
    DontKnow,
    Edit,
    HelpMe,
    MarkTbd,
    Modality,
    Regenerate,
    Reject,
    Resume,
    Retry,
    SectionConfig,
    SectionEvent,
    SectionState,
    Skip,
    Submit,
    UserMessage,
    WriteMyself,
)

S = SectionState

# Commands are only recognised in short utterances; long replies are treated as content.
_MAX_COMMAND_WORDS = 8

_SKIP = re.compile(
    r"\b(skip|later|next|come back to (this|it)|move on|preskoc\w*|pozdeji|dalsi|vratime se|jdeme dal)\b"
)
_DONT_KNOW = re.compile(
    r"\b(i ?don'?t know|dont know|no idea|not sure|unsure|no clue|nevim|netusim|nejsem si jist\w*|"
    r"nemam (tuseni|predstavu))\b"
)
_UNSURE_VALUE = re.compile(
    r"^(?:i'?m |i am )?(?:not sure|unsure|nevim|nejsem si jist\w*)?[\s,.;:!-]*"
    r"(?:maybe|perhaps|probably|possibly|i think|mozna|asi|nejspis|myslim ze)\s+(?P<value>.+?)\s*[?.!]*$"
)
_OWNER = (
    re.compile(r"^(?:you should |we should |please )?ask (?P<owner>.+?)\s*[.!]*$"),
    re.compile(r"^(?P<owner>.+?) (?:would|will|should|might|may) know\b.*$"),
    re.compile(r"^(?:zeptej(?:te)? se|zeptame se|zeptat se) (?P<owner>.+?)\s*[.!]*$"),
    re.compile(r"^(?:to )?(?P<owner>.+?) (?:to )?(?:bude|by mel|by mela|muze) vedet\b.*$"),
)
_MARK_TBD = re.compile(r"\b(tbd|to be decided|mark (it )?(as )?(open|tbd)|open item|otevren\w* bod|doresime pozdeji)\b")
_HELP = re.compile(r"\b(help( me)?|look (it )?up|search|find (it|him|her)|pomoz\w*|vyhledej|najdi)\b")
_AFFIRM = re.compile(
    r"^(yes|yeah|yep|yup|ok|okay|sure|correct|right|exactly|perfect|accept( it)?|looks good|sounds good|"
    r"that'?s (right|it|correct|fine)|ano|jo|jj|jasne|souhlas\w*|v poradku|dobre|presne|spravne|"
    r"vypada (to )?dobre|prijmout|beru)"
    r"(?:[\s,]+(?:thanks|thank you|please|dekuji|diky|go ahead|save it|ulozit))?$"
)
_NEGATE = re.compile(r"^(no|nope|nah|wrong|that'?s wrong|not (right|correct)|ne|nene|spatne|to neni ono)$")
_NEGATE_PREFIX = re.compile(r"^(?:no|nope|ne)[\s,.;:!-]+")
_CANCEL = re.compile(r"^(cancel|never ?mind|stop|forget it|zrus\w*|nech to byt|zpet|back)$")
_RETRY = re.compile(r"\b(try again|retry|once more|zkus(te)? (to )?znovu|znovu)\b")
_REGENERATE = re.compile(
    r"\b(another (one|version|option)|regenerate|different (one|version)|jin\w+ (variant\w*|verz\w*))\b"
)
_WRITE_MYSELF = re.compile(r"\b(i'?ll write it|let me write|write it myself|napisu (to )?sam\w*|napisu si to)\b")
_EDIT = re.compile(r"^(edit( it)?|change it|let me edit|upravit|zmenit|uprav to)$")


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, strip diacritics, compact whitespace — and remember each output char's source index."""
    chars: list[str] = []
    index_map: list[int] = []
    for index, ch in enumerate(text.replace("’", "'").replace("‘", "'")):
        base = "".join(c for c in unicodedata.normalize("NFD", ch.lower()) if unicodedata.category(c) != "Mn")
        for out in base:
            if out.isspace():
                if not chars or chars[-1] == " ":
                    continue
                out = " "
            chars.append(out)
            index_map.append(index)
    while chars and chars[-1] == " ":
        chars.pop()
        index_map.pop()
    return "".join(chars), index_map


def _original_span(text: str, index_map: list[int], start: int, end: int) -> str:
    if start >= end:
        return ""
    return text[index_map[start] : index_map[end - 1] + 1].strip(" ,.;:!?\"'")


_BARE_CHARS = " .,!?;:"
_NOT_AN_OWNER = frozenset({"who", "nobody", "no one", "someone", "somebody", "kdo", "nikdo", "nekdo", "i", "we"})


def _bare(normalized: str) -> str:
    return normalized.strip(_BARE_CHARS)


@dataclass(frozen=True)
class IntentResult:
    events: tuple[SectionEvent, ...]
    needs_model: bool = False


def _content_event(text: str, kind: SectionKind, modality: Modality, *, low_confidence: bool = False) -> SectionEvent:
    if kind == "simple":
        return Submit(clean_direct_answer_value(text), modality=modality, low_confidence=low_confidence)
    return UserMessage(text, modality=modality)


def map_utterance(text: str, *, state: SectionState, kind: SectionKind, modality: Modality = "chat") -> IntentResult:
    """Deterministic mapping. `needs_model` flags simple-field replies the keywords could not pin down."""
    raw = text.strip()
    if not raw:
        return IntentResult(())
    normalized, full_index_map = _normalize_with_map(raw)
    bare = _bare(normalized)
    lead = len(normalized) - len(normalized.lstrip(_BARE_CHARS))
    index_map = full_index_map[lead:]
    is_command_length = len(bare.split()) <= _MAX_COMMAND_WORDS

    if is_command_length:
        # "I don't know, skip it" -> SKIP: the explicit action wins over the uncertainty.
        if _SKIP.search(bare):
            return IntentResult((Skip(),))
        if _CANCEL.match(bare):
            return IntentResult((Cancel(),))
        for pattern in _OWNER:
            if match := pattern.match(bare):
                owner = _original_span(raw, index_map, match.start("owner"), match.end("owner"))
                owner_key = _bare(_normalize_with_map(owner)[0])
                if owner and owner_key not in _NOT_AN_OWNER and not _DONT_KNOW.search(owner_key):
                    return IntentResult((MarkTbd(owner=owner, note=raw),))
        if _MARK_TBD.search(bare):
            return IntentResult((MarkTbd(note=None if _MARK_TBD.fullmatch(bare) else raw),))
        if match := _UNSURE_VALUE.match(bare):
            value = _original_span(raw, index_map, match.start("value"), match.end("value"))
            if value:
                return _with_resume(state, _content_event(value, kind, modality, low_confidence=True))
        if _DONT_KNOW.search(bare):
            return IntentResult((DontKnow(),))
        stateful = _state_command(bare, state, kind)
        if stateful is not None:
            return IntentResult((stateful,))

    if state is S.CONFIRMING:
        value = _NEGATE_PREFIX.sub("", raw).strip() if _NEGATE_PREFIX.match(normalized) else raw
        return IntentResult((Submit(clean_direct_answer_value(value), modality=modality),))

    needs_model = kind == "simple" and not is_plausible_direct_answer(raw)
    return IntentResult(_with_resume(state, _content_event(raw, kind, modality)).events, needs_model=needs_model)


def _with_resume(state: SectionState, event: SectionEvent) -> IntentResult:
    # A skipped section only reacts to RESUME; answering it implies resuming first.
    if state is S.SKIPPED:
        return IntentResult((Resume(), event))
    return IntentResult((event,))


def _state_command(bare: str, state: SectionState, kind: SectionKind) -> SectionEvent | None:
    if state is S.CONFIRMING:
        if _AFFIRM.match(bare):
            return Confirm()
        if _NEGATE.match(bare):
            return Reject()
        return None
    if state is S.PROPOSED:
        if _AFFIRM.match(bare):
            return Accept()
        if _NEGATE.match(bare):
            return Reject()
        if _REGENERATE.search(bare):
            return Regenerate()
        if _EDIT.match(bare):
            return Edit()
        return None
    if state is S.UNSURE:
        if _HELP.search(bare) or _AFFIRM.match(bare):
            return HelpMe()
        return None
    if state is S.GENERATION_FAILED:
        if _RETRY.search(bare):
            return Retry()
        if _WRITE_MYSELF.search(bare):
            return WriteMyself()
        return None
    if state is S.GATHERING and _WRITE_MYSELF.search(bare):
        return WriteMyself()
    if state is S.ACCEPTED and _EDIT.match(bare):
        return Edit()
    if state in (S.TBD, S.SKIPPED) and _AFFIRM.match(bare):
        return Resume()
    return None


ModelClassifier = Callable[[str, SectionConfig], Awaitable[SectionEvent | None]]


async def resolve_utterance(
    text: str,
    *,
    state: SectionState,
    config: SectionConfig,
    modality: Modality = "chat",
    model_classifier: ModelClassifier | None = None,
) -> tuple[SectionEvent, ...]:
    """Keyword mapping first; a small model only for ambiguous simple-field replies.

    The model's answer becomes a typed event too, and anything it is unsure about is submitted with
    `low_confidence=True` so the machine reads it back for confirmation instead of committing.
    """
    result = map_utterance(text, state=state, kind=config.kind, modality=modality)
    if not result.needs_model or model_classifier is None:
        return result.events
    event = await model_classifier(text, config)
    if event is None:
        return result.events
    if isinstance(event, Submit):
        event = Submit(event.value, modality=modality, low_confidence=event.low_confidence or modality == "voice")
    return _with_resume(state, event).events
