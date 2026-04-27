"""Shared utility functions used across backend modules."""

import re

from google.adk.sessions import Session

_GCS_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sanitize_gcs_segment(value: str, *, field_name: str = "path segment") -> str:
    """Validate a single GCS object path segment."""
    segment = value.strip()
    if not _GCS_SEGMENT_RE.fullmatch(segment) or segment in {".", ".."}:
        raise ValueError(f"Invalid {field_name}")
    return segment


def sanitize_gcs_filename(filename: str) -> str:
    """Return a safe basename for a user-supplied upload filename."""
    normalized = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return sanitize_gcs_segment(normalized, field_name="filename")


def extract_conversation_text(session: Session) -> str:
    """Flatten a session's events into a plain text transcript.

    Returns lines in the form "User: ..." / "Consultant: ..." joined by newlines.
    """
    lines: list[str] = []
    for event in session.events or []:
        if not event.content or not event.content.parts:
            continue
        role = event.content.role or "unknown"
        text = "".join(p.text for p in event.content.parts if p.text).strip()
        if text:
            label = "User" if role == "user" else "Consultant"
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def format_prompt_data_lines(text: str, *, default_label: str = "Transcript line") -> str:
    """Prefix free-form user-controlled prompt data with stable line labels."""
    labeled_lines: list[str] = []
    known_prefixes = ("User:", "Consultant:", "Assistant:", "AI:", "System:")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            labeled_lines.append("")
        elif stripped.startswith(known_prefixes):
            labeled_lines.append(stripped)
        else:
            labeled_lines.append(f"{default_label}: {stripped}")
    return "\n".join(labeled_lines).strip()
