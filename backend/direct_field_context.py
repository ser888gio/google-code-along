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
        lines.append("Context from the Requirements Specification form, entered manually by the user.")
    if fields:
        lines.append("Treat these fields as already provided and do not ask for them again:")
        for key, label in labels.items():
            value = fields.get(key)
            if value:
                lines.append(f"- {label}: {value}")

    if deferred:
        lines.append(
            "The user deferred these fields. Do not ask for them again immediately; "
            "revisit them during wrap-up if still required:"
        )
        for key in deferred:
            lines.append(f"- {labels[key]}")

    return "\n".join(lines) + f"\n\nUser message:\n{message}"


def _render_workflow_context(
    context: Mapping[str, object],
    labels: Mapping[str, str],
) -> list[str]:
    """Render the backend-owned workflow cursor into hidden agent context."""
    phase = str(context.get("phase") or "discovery")
    lines = ["Workflow context:", f"- Phase: {phase}"]

    if phase == "wrap_up":
        lines.append("- Required fields are all answered, deferred, or not applicable.")
        lines.append("- Do not ask ordinary discovery questions.")
        lines.append("- Summarize what was captured in one short paragraph.")
        deferred_raw = context.get("deferred_fields", []) or []
        deferred = [str(k) for k in deferred_raw] if isinstance(deferred_raw, (list, tuple)) else []
        if deferred:
            lines.append("- List deferred or unknown fields explicitly:")
            for key in deferred:
                lines.append(f"  - {labels.get(key, key)}")
        lines.append("- Ask whether the user wants to fill any of them now, or finalize with them as open questions.")
        return lines

    active_field = context.get("active_field")
    if isinstance(active_field, str) and active_field:
        lines.append(
            f"- Active field: {labels.get(active_field, active_field)}. Ask exactly one question about this field."
        )
    else:
        lines.append("- No active field. Do not invent a new field question.")

    if context.get("clarification_requested"):
        lines.append("- The user just asked for clarification. Explain the active field briefly, then ask again.")

    active_gaps = context.get("active_field_coverage_gaps") or []
    if isinstance(active_gaps, list) and active_gaps:
        gap_phrases = ", ".join(str(g) for g in active_gaps if str(g).strip())
        if gap_phrases:
            lines.append(
                "- The user's last answer did not fully cover this field. "
                f"Missing aspects: {gap_phrases}. Ask one short, conversational "
                "follow-up that targets the most important missing aspect. "
                "Do NOT cite the rubric verbatim or list every missing item."
            )

    miss_count = context.get("miss_count")
    if isinstance(miss_count, int) and miss_count >= 2:
        lines.append(f"- The user has missed this field {miss_count} times. Offer to mark it unknown or fill it later.")

    answered = context.get("answered_fields")
    if isinstance(answered, Mapping) and answered:
        lines.append("- Already answered, do not re-ask:")
        for key, value in answered.items():
            if value is not None and str(value).strip():
                lines.append(f"  - {labels.get(str(key), str(key))}: {value}")

    deferred_raw = context.get("deferred_fields", []) or []
    deferred = [str(k) for k in deferred_raw] if isinstance(deferred_raw, (list, tuple)) else []
    if deferred:
        lines.append("- Deferred, do not ask now; revisit at wrap-up:")
        for key in deferred:
            lines.append(f"  - {labels.get(key, key)}")

    if context.get("ready_to_finalize"):
        lines.append("- The user chose to finalize. Summarize briefly and emit [FINALIZING] on its own line.")

    return lines
