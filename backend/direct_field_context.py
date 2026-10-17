"""Helpers for passing manually-entered form fields into agent context."""

from collections.abc import Mapping

from field_schema import DIRECT_FIELD_LABELS


def clean_direct_fields(fields: Mapping[str, object] | None) -> dict[str, str]:
    """Return known, non-empty direct-input fields as strings."""
    if not fields:
        return {}

    cleaned: dict[str, str] = {}
    for key, value in fields.items():
        if key not in DIRECT_FIELD_LABELS or value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    return cleaned


def clean_deferred_fields(
    fields: list[str] | None,
    field_labels: Mapping[str, str] | None = None,
) -> list[str]:
    """Return known fields the user chose to defer."""
    if not fields:
        return []
    labels = field_labels or DIRECT_FIELD_LABELS
    return [key for key in fields if key in labels]


def merge_direct_fields(
    stored: Mapping[str, object] | None,
    incoming: Mapping[str, object] | None,
) -> dict[str, str]:
    """Merge stored and freshly submitted direct fields, preferring incoming."""
    merged = clean_direct_fields(stored)
    if not incoming:
        return merged

    for key, value in incoming.items():
        if key not in DIRECT_FIELD_LABELS or value is None:
            continue
        text = str(value).strip()
        if text:
            merged[key] = text
        else:
            merged.pop(key, None)
    return merged


def build_augmented_user_message(
    message: str,
    direct_fields: Mapping[str, str],
    deferred_fields: list[str] | None = None,
    *,
    workflow_context: Mapping[str, object] | None = None,
    field_labels: Mapping[str, str] | None = None,
) -> str:
    """Add hidden form context so the agent does not ask for fields already typed."""
    labels = field_labels or DIRECT_FIELD_LABELS
    fields = clean_direct_fields(direct_fields)
    deferred = clean_deferred_fields(deferred_fields, labels)
    if not fields and not deferred and not workflow_context:
        return message

    lines = []
    if workflow_context:
        lines.extend(_render_workflow_context(workflow_context, labels))

    if fields or deferred:
        lines.extend(_render_direct_form_context(fields, deferred, labels))

    return "\n".join(lines) + f"\n\nUser message:\n{message}"


def _render_direct_form_context(
    fields: Mapping[str, str],
    deferred: list[str],
    labels: Mapping[str, str],
) -> list[str]:
    lines = ["Context from the Requirements Specification form, entered manually by the user."]
    if fields:
        lines.extend(_render_answered_direct_fields(fields, labels))
    if deferred:
        lines.extend(_render_deferred_direct_fields(deferred, labels))
    return lines


def _render_answered_direct_fields(fields: Mapping[str, str], labels: Mapping[str, str]) -> list[str]:
    lines = ["Treat these fields as already provided and do not ask for them again:"]
    for key, label in labels.items():
        value = fields.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    return lines


def _render_deferred_direct_fields(deferred: list[str], labels: Mapping[str, str]) -> list[str]:
    lines = [
        "The user deferred these fields. Do not ask for them again immediately; "
        "revisit them during wrap-up if still required:"
    ]
    lines.extend(f"- {labels[key]}" for key in deferred)
    return lines


def _field_key_list(value: object) -> list[str]:
    return [str(key) for key in value] if isinstance(value, (list, tuple)) else []


_WRAP_UP_CHOICES = {
    True: (
        '["Dokončit s otevřenými otázkami", "Doplnit chybějící údaje"]',
        '["Finalize with open questions", "Fill in the missing details"]',
    ),
    False: (
        '["Dokončit specifikaci", "Doplnit další údaje"]',
        '["Finalize the specification", "Add more details"]',
    ),
}


def _render_wrap_up_context(context: Mapping[str, object], labels: Mapping[str, str]) -> list[str]:
    lines = [
        "- Required fields are all answered, deferred, or not applicable.",
        "- Do not ask ordinary discovery questions.",
        "- Summarize what was captured in one short paragraph.",
    ]
    deferred = _field_key_list(context.get("deferred_fields", []) or [])
    if deferred:
        lines.append("- List deferred or unknown fields explicitly:")
        lines.extend(f"  - {labels.get(key, key)}" for key in deferred)
        lines.append(
            "- Ask one yes/no question: should you finalize now, with these fields as open questions? "
            "Mention that the user can instead give the missing details."
        )
    else:
        lines.append(
            "- Ask one yes/no question: should you finalize the specification now? "
            "Mention that the user can instead add more details."
        )
    # Fixed texts: the UI sends a clicked choice verbatim, and chat_turn matches these words.
    cs_choices, en_choices = _WRAP_UP_CHOICES[bool(deferred)]
    lines.append(f"- End your reply with exactly this block if you reply in Czech: <choices>{cs_choices}</choices>")
    lines.append(f"- Or exactly this one if you reply in English: <choices>{en_choices}</choices>")
    return lines


def _render_active_field_context(context: Mapping[str, object], labels: Mapping[str, str]) -> list[str]:
    active_field = context.get("active_field")
    if isinstance(active_field, str) and active_field:
        return [f"- Active field: {labels.get(active_field, active_field)}. Ask exactly one question about this field."]
    return ["- No active field. Do not invent a new field question."]


def _render_gap_context(context: Mapping[str, object]) -> list[str]:
    active_gaps = context.get("active_field_coverage_gaps") or []
    if not isinstance(active_gaps, list) or not active_gaps:
        return []

    gap_phrases = ", ".join(str(g) for g in active_gaps if str(g).strip())
    if not gap_phrases:
        return []

    return [
        "- The user's last answer did not fully cover this field. "
        f"Missing aspects: {gap_phrases}. Ask one short, conversational "
        "follow-up that targets the most important missing aspect. "
        "Do NOT cite the rubric verbatim or list every missing item."
    ]


def _render_answered_workflow_fields(
    context: Mapping[str, object],
    labels: Mapping[str, str],
) -> list[str]:
    answered = context.get("answered_fields")
    if not isinstance(answered, Mapping) or not answered:
        return []

    lines = ["- Already answered, do not re-ask:"]
    for key, value in answered.items():
        if value is not None and str(value).strip():
            lines.append(f"  - {labels.get(str(key), str(key))}: {value}")
    return lines


def _render_deferred_workflow_fields(
    context: Mapping[str, object],
    labels: Mapping[str, str],
) -> list[str]:
    deferred = _field_key_list(context.get("deferred_fields", []) or [])
    if not deferred:
        return []

    lines = ["- Deferred, do not ask now; revisit at wrap-up:"]
    lines.extend(f"  - {labels.get(key, key)}" for key in deferred)
    return lines


def _render_workflow_context(
    context: Mapping[str, object],
    labels: Mapping[str, str],
) -> list[str]:
    """Render the backend-owned workflow cursor into hidden agent context."""
    phase = str(context.get("phase") or "discovery")
    lines = ["Workflow context:", f"- Phase: {phase}"]

    if phase == "wrap_up":
        lines.extend(_render_wrap_up_context(context, labels))
        return lines

    lines.extend(_render_active_field_context(context, labels))

    if context.get("clarification_requested"):
        lines.append("- The user just asked for clarification. Explain the active field briefly, then ask again.")

    lines.extend(_render_gap_context(context))

    miss_count = context.get("miss_count")
    if isinstance(miss_count, int) and miss_count >= 2:
        lines.append(f"- The user has missed this field {miss_count} times. Offer to mark it unknown or fill it later.")

    lines.extend(_render_answered_workflow_fields(context, labels))
    lines.extend(_render_deferred_workflow_fields(context, labels))

    if context.get("ready_to_finalize"):
        lines.append("- The user chose to finalize. Summarize briefly and emit [FINALIZING] on its own line.")

    return lines
