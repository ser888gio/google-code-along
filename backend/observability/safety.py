"""Safety guardrails for known-bad prompts and runaway session cost."""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass

from config import COST_CIRCUIT_BREAKER_USD
from logger import get_logger
from opentelemetry import trace

from observability.metrics import (
    record_cost_circuit_tripped,
    record_prompt_injection_attempt,
)

logger = get_logger(__name__)

FRIENDLY_COST_ERROR = (
    "I paused this session because it hit the configured cost safety limit. "
    "Please start a new session or contact support if this looks wrong."
)

FRIENDLY_PROMPT_ERROR = (
    "I can't help with requests to bypass instructions, reveal hidden prompts, "
    "or extract private data. I can still help with your requirements specification."
)


@dataclass(frozen=True)
class PromptRisk:
    category: str
    pattern: str


class CostCircuitBreakerTripped(RuntimeError):
    """Raised when a session exceeds the configured cumulative cost limit."""

    def __init__(self, session_id: str, cost_usd: float, limit_usd: float) -> None:
        self.session_id = session_id
        self.cost_usd = cost_usd
        self.limit_usd = limit_usd
        super().__init__(f"session {session_id} exceeded cost limit: {cost_usd:.4f} > {limit_usd:.4f}")


class UnsafePromptBlocked(ValueError):
    """Raised when deterministic prompt safety checks block user input."""

    def __init__(self, risk: PromptRisk) -> None:
        self.risk = risk
        super().__init__(f"blocked unsafe prompt category={risk.category}")


_session_cost_usd: dict[str, float] = {}
_tripped_sessions: set[str] = set()
_lock = threading.RLock()

_PROMPT_RISKS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(ignore|forget|override)\b.{0,80}"
            r"\b(previous|prior|above|system|developer)\b.{0,40}"
            r"\b(instructions?|rules?)\b",
            re.I | re.S,
        ),
        "prompt_injection",
    ),
    (
        re.compile(
            r"\b(system|developer|hidden|initial)\b.{0,50}" r"\b(prompt|instructions?|message|policy)\b",
            re.I | re.S,
        ),
        "prompt_extraction",
    ),
    (
        re.compile(
            r"\b(reveal|print|dump|show|exfiltrate|leak)\b.{0,80}"
            r"\b(prompt|instructions?|secrets?|api[_ -]?keys?|tokens?|"
            r"passwords?|private data|pii)\b",
            re.I | re.S,
        ),
        "data_exfiltration",
    ),
    (
        re.compile(
            r"\b(jailbreak|DAN mode|developer mode|god mode|disable safety|" r"bypass safety|no filters?|uncensored)\b",
            re.I,
        ),
        "jailbreak",
    ),
    (
        re.compile(
            r"\b(base64|rot13|hex encode|obfuscate)\b.{0,80}" r"\b(secret|prompt|password|token|api[_ -]?key|policy)\b",
            re.I | re.S,
        ),
        "obfuscated_exfiltration",
    ),
    (
        re.compile(
            r"\b(list|extract|export|show)\b.{0,80}\b(all|every)\b.{0,80}"
            r"\b(emails?|phone numbers?|ssn|social security|credit cards?|"
            r"customer records?|employee records?)\b",
            re.I | re.S,
        ),
        "pii_extraction",
    ),
    (
        re.compile(r"\bBEGIN\s+(SYSTEM|DEVELOPER|OVERRIDE)\s+PROMPT\b", re.I),
        "role_injection",
    ),
]


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def configured_cost_limit_usd() -> float:
    return max(0.0, float(COST_CIRCUIT_BREAKER_USD or 0.0))


def current_session_cost(session_id: str) -> float:
    with _lock:
        return round(_session_cost_usd.get(session_id, 0.0), 8)


def reset_session_cost(session_id: str) -> None:
    with _lock:
        _session_cost_usd.pop(session_id, None)
        _tripped_sessions.discard(session_id)


def assert_session_within_budget(session_id: str) -> None:
    limit = configured_cost_limit_usd()
    if limit <= 0:
        return
    cost = current_session_cost(session_id)
    if cost > limit:
        _trip_cost_circuit(session_id=session_id, cost_usd=cost, limit_usd=limit)


def add_session_cost(session_id: str | None, cost_usd: float) -> float:
    """Accumulate cost and raise when a session crosses the configured limit."""
    if not session_id or cost_usd <= 0:
        return 0.0

    with _lock:
        cumulative = round(_session_cost_usd.get(session_id, 0.0) + cost_usd, 8)
        _session_cost_usd[session_id] = cumulative

    limit = configured_cost_limit_usd()
    if limit > 0 and cumulative > limit:
        _trip_cost_circuit(session_id=session_id, cost_usd=cumulative, limit_usd=limit)
    return cumulative


def _trip_cost_circuit(*, session_id: str, cost_usd: float, limit_usd: float) -> None:
    sid_hash = _hash_id(session_id)
    with _lock:
        first_trip = session_id not in _tripped_sessions
        _tripped_sessions.add(session_id)

    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("rs.safety.cost_circuit_tripped", True)
        span.set_attribute("rs.safety.session_cost_usd", cost_usd)
        span.set_attribute("rs.safety.cost_limit_usd", limit_usd)

    if first_trip:
        record_cost_circuit_tripped(session_id_hash=sid_hash)
        logger.warning(
            "Cost circuit breaker tripped: "
            f"event=rs.safety.cost_circuit_tripped session_id_hash={sid_hash} "
            f"cost_usd={cost_usd:.6f} limit_usd={limit_usd:.2f}"
        )
    raise CostCircuitBreakerTripped(session_id, cost_usd, limit_usd)


def detect_unsafe_prompt(text: str) -> PromptRisk | None:
    normalized = (text or "").strip()
    if not normalized:
        return None
    for pattern, category in _PROMPT_RISKS:
        if pattern.search(normalized):
            return PromptRisk(category=category, pattern=pattern.pattern)
    return None


def check_user_prompt_or_raise(text: str, *, session_id: str | None = None) -> None:
    risk = detect_unsafe_prompt(text)
    if risk is None:
        return

    record_prompt_injection_attempt(blocked=True, category=risk.category)
    sid_hash = _hash_id(session_id) if session_id else "unknown"
    logger.warning(
        "Unsafe prompt blocked: "
        f"event=rs.safety.prompt_injection_blocked session_id_hash={sid_hash} "
        f"category={risk.category}"
    )
    raise UnsafePromptBlocked(risk)
