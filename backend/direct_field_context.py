"""Helpers for passing manually-entered form fields into agent context."""

from collections.abc import Mapping


DIRECT_FIELD_LABELS: dict[str, str] = {
    "use_case_title": "Use Case Title",
    "department": "Customer Department",
    "requestor": "Requestor",
    "product_owner": "Product Owner",
    "saved_time_hours_per_year": "Saved Time (hours/year)",
    "cost_saving": "Cost Saving",
    "revenue_increase": "Revenue Increase",
    "comments": "Comments",
    "attachments": "Attachments",
}


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


def build_augmented_user_message(message: str, direct_fields: Mapping[str, str]) -> str:
    """Add hidden form context so the agent does not ask for fields already typed."""
    fields = clean_direct_fields(direct_fields)
    if not fields:
        return message

    lines = [
        "Context from the Requirements Specification form, entered manually by the user.",
        "Treat these fields as already provided and do not ask for them again:",
    ]
    for key, label in DIRECT_FIELD_LABELS.items():
        value = fields.get(key)
        if value:
            lines.append(f"- {label}: {value}")

    return "\n".join(lines) + f"\n\nUser message:\n{message}"
