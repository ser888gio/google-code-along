"""Minimal local redaction helpers for persisted conversation text.

This is intentionally conservative and dependency-free. It removes common PII
patterns before text is written to Firestore, and stores a hash of the original
text for deduplication/audit without retaining the raw value.
"""

from __future__ import annotations

import hashlib
import re

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)",
)
_CREDIT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
_API_KEY_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+",
)


def _mask_credit_card(match: re.Match[str]) -> str:
    value = match.group(0)
    digits = re.sub(r"\D", "", value)
    if len(digits) < 13:
        return value
    return "[REDACTED_CARD]"


def redact_text(text: str | None) -> str:
    """Return a redacted copy of *text* suitable for persistence."""
    if not text:
        return ""

    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = _API_KEY_RE.sub("[REDACTED_SECRET]", redacted)
    redacted = _CREDIT_CARD_RE.sub(_mask_credit_card, redacted)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def hash_text(text: str | None) -> str:
    """Hash raw text without storing it."""
    value = text or ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
