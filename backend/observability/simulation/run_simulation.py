"""Simulate business users interviewing with the RS assistant end to end.

An LLM persona drives the same HTTP calls the frontend makes (chat stream,
field extraction, suggestion accepts, thumbs, DOCX download, session rating),
so every simulated session also lands in Firestore/OTel like a real one.

Only user *intent* is configured (finish / early_exit / disconnect); whether a
session actually succeeds is decided by the real backend. Each run writes one
JSON result; ``report`` aggregates them into CSV plus summary metrics.

Usage (from backend/):
    SIM_TARGET_URL=http://localhost:8080 python -m observability.simulation.run_simulation
    python -m observability.simulation.run_simulation report sim_results
"""

from __future__ import annotations

import csv
import json
import logging
import os
import random
import statistics
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar, cast

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

RESULTS_PREFIX = "simulations/"
CHURN_RATING = 2


@dataclass(frozen=True)
class Persona:
    name: str
    lang: str
    style: str
    max_turns: int
    accept_rate: float


PERSONAS = [
    Persona("cooperative_expert", "en", "You know your process well and answer fully with concrete numbers.", 45, 0.9),
    Persona("czech_manager", "cs", "You answer clearly in 1-3 sentences, focused on business value.", 45, 0.8),
    Persona("terse_user", "en", "You are busy. You answer in a few words and rarely elaborate.", 35, 0.6),
    Persona("vague_user", "cs", "You are unsure about many details and often say you will check later.", 35, 0.5),
    Persona(
        "impatient_user",
        "en",
        "You are impatient. If the assistant repeats itself or asks too much, you get annoyed.",
        20,
        0.4,
    ),
    Persona(
        "tech_lead",
        "en",
        "You are technical and keep asking which database, cloud or architecture to use. "
        "You still answer business questions when redirected.",
        40,
        0.7,
    ),
    Persona(
        "procurement_officer",
        "cs",
        "You are detail- and compliance-oriented, mention approval limits, contracts and audit trails.",
        45,
        0.8,
    ),
    Persona("hr_specialist", "cs", "You are non-technical and describe things from the employee's view.", 40, 0.7),
    Persona(
        "plant_shift_lead",
        "cs",
        "You are practical and short on time, you describe the shop-floor reality in plain words.",
        30,
        0.6,
    ),
    Persona("finance_controller", "en", "You think in numbers, KPIs, costs and audit requirements.", 45, 0.85),
    Persona(
        "first_time_user",
        "en",
        "You have never used such a tool, sometimes ask how it works and what happens with your answers.",
        40,
        0.6,
    ),
    Persona(
        "sales_manager",
        "cs",
        "You focus on customers and revenue and sometimes drift off-topic to sales anecdotes.",
        35,
        0.6,
    ),
]

PROJECTS: dict[str, list[str]] = {
    "procurement": [
        "Supplier onboarding: collecting company data, certificates and bank details, today by e-mail and PDFs.",
        "Purchase request approval with limits by amount, today paper forms signed by managers.",
        "Approval workflow for supplier invoices, today done by e-mail and Excel.",
    ],
    "production": [
        "Digital shift handover log for the assembly line, today a paper notebook.",
        "Machine downtime reporting with reasons and durations, today written on whiteboards.",
        "Quality defect tracking from detection to corrective action, today in several Excel files.",
    ],
    "logistics": [
        "Booking of time slots for inbound truck deliveries, today by phone with the gatekeeper.",
        "Tracking of returnable packaging (racks, boxes) with suppliers, today a monthly manual count.",
        "Spare-parts stock monitoring in a regional warehouse, today a weekly manual count in Excel.",
    ],
    "hr": [
        "Employee leave requests and approvals, today e-mails to the manager and HR.",
        "Internal job postings and applications, today on the intranet notice board and by e-mail.",
        "Yearly performance review cycle with goals and evaluations, today Word templates.",
        "Onboarding checklist for new employees across HR, IT and facility, today on paper forms.",
        "Planning of internal training courses and attendance, today coordinated by e-mail.",
    ],
    "finance": [
        "Travel expense claims with receipts and approvals, today paper forms and scanned receipts.",
        "Budget change requests between cost centres, today e-mails with Excel attachments.",
    ],
    "sales": [
        "Dealer order tracking from order to delivery, today phone calls and e-mails.",
        "Warranty claim handling between dealers and the manufacturer, today a mix of e-mails and an old tool.",
        "Collecting and evaluating customer feedback after service visits, today paper questionnaires.",
        "Tracking of customer complaints in after-sales service, today scattered across e-mails and notes.",
    ],
    "it": [
        "Software licence requests and renewals, today free-text tickets and a shared Excel.",
        "Hardware asset register for laptops, phones and monitors, today an outdated spreadsheet.",
        "Requests for IT access rights (applications, VPN, shared drives), today sent as free-text tickets.",
    ],
    "facility": [
        "Booking of meeting rooms and parking places, today a shared calendar and a paper list at reception.",
        "Maintenance requests for buildings (lights, heating, repairs), today phone calls to the caretaker.",
        "Booking system for the company vehicle fleet (about 120 cars), today managed in a shared calendar.",
    ],
    "compliance": [
        "Handling GDPR data-access requests from customers within the legal deadline, today by e-mail.",
        "Tracking internal audit findings and their remediation, today an Excel owned by one person.",
    ],
    "marketing": [
        "Approval of marketing campaigns across brand, legal and budget owners, today e-mail chains.",
    ],
}


@dataclass(frozen=True)
class SimUser:
    user_id: str
    persona: Persona
    department: str


def build_user_pool(size: int = 40, seed: int = 42) -> list[SimUser]:
    rng = random.Random(seed)
    departments = sorted(PROJECTS)
    return [SimUser(f"sim-u{i:02d}", rng.choice(PERSONAS), rng.choice(departments)) for i in range(1, size + 1)]


USERS = build_user_pool()

Intent = Literal["finish", "early_exit", "disconnect"]


def parse_intent_mix(raw: str) -> dict[str, float]:
    mix = {}
    for part in raw.split(","):
        name, weight = part.split(":")
        mix[name.strip()] = float(weight)
    return mix


class PersonaTurn(BaseModel):
    message: str
    vote_on_last_reply: Literal["up", "down", "none"]
    sentiment: Literal["positive", "neutral", "negative"]
    quit: bool


class PersonaVerdict(BaseModel):
    rating: int
    comment: str
    goal_achieved: bool
    stayed_business_focused: bool


@dataclass
class SessionResult:
    session_id: str
    user_id: str
    persona: str
    department: str
    lang: str
    project: str
    intended_outcome: str
    started_at: str
    outcome: str = "turn_cap"
    user_turns: int = 0
    duration_s: float = 0.0
    finalized: bool = False
    analysis_status: str = "not_found"
    time_to_analysis_s: float | None = None
    converted: bool = False
    ttft_ms: list[int] = field(default_factory=list)
    latency_ms: list[int] = field(default_factory=list)
    discovery_completeness: int = 0
    accepted_completeness: int = 0
    suggestions_accepted: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    sentiment: dict[str, int] = field(default_factory=lambda: {"positive": 0, "neutral": 0, "negative": 0})
    choices_shown: int = 0
    errors: int = 0
    user_chars: int = 0
    assistant_chars: int = 0
    rating: int | None = None
    rating_comment: str = ""
    goal_achieved: bool | None = None
    stayed_business_focused: bool | None = None


def _system_instruction(persona: Persona, department: str, project: str) -> str:
    language = "Czech" if persona.lang == "cs" else "English"
    return (
        f"You are role-playing an employee of the {department} department using an AI consultant that gathers "
        f"requirements for a requirement specification. Your project: {project} {persona.style} "
        f"Write in {language}. Invent plausible, consistent details when asked. Never mention you are an AI. "
        "Your goal is a finished specification. When the consultant offers choices, pick one of them. "
        "When asked whether to finalize/generate the specification, agree. "
        "Set quit=true only if you would genuinely give up on the tool. "
        "sentiment is how you feel right now about the conversation."
    )


def _transcript(history: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"{speaker}: {text}" for speaker, text in history)


class PersonaModel:
    def __init__(self, persona: Persona, department: str, project: str) -> None:
        from config import GOOGLE_API_KEY, MODEL_DISCOVERY
        from google import genai

        self._client = genai.Client(api_key=GOOGLE_API_KEY)
        self._model = os.getenv("SIM_PERSONA_MODEL", MODEL_DISCOVERY)
        self._system = _system_instruction(persona, department, project)

    def _ask(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self._system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return schema.model_validate_json(response.text or "")

    def next_turn(self, history: list[tuple[str, str]], choices: list[str]) -> PersonaTurn:
        if not history:
            prompt = "Start the conversation: introduce your need in your own words. vote_on_last_reply=none."
        else:
            options = f"\nOffered choices: {choices}" if choices else ""
            prompt = f"Conversation so far:\n{_transcript(history)}{options}\n\nWrite your next message."
        return self._ask(prompt, PersonaTurn)

    def verdict(self, history: list[tuple[str, str]]) -> PersonaVerdict:
        prompt = (
            f"Conversation:\n{_transcript(history)}\n\n"
            "The session is over. Rate the tool 1-5 as this user would, with a one-sentence comment. "
            "goal_achieved: did you get a usable specification? "
            "stayed_business_focused: did the consultant avoid choosing technology/architecture for you?"
        )
        verdict = self._ask(prompt, PersonaVerdict)
        verdict.rating = max(1, min(5, verdict.rating))
        return verdict


@dataclass
class StreamReply:
    message_id: str = ""
    text: str = ""
    choices: list[str] = field(default_factory=list)
    finalizing: bool = False
    error: str | None = None
    ttft_ms: int | None = None
    latency_ms: int = 0


def parse_sse_events(lines: list[str]) -> list[dict]:
    events = []
    for line in lines:
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            events.append(json.loads(line[len("data: ") :]))
        except json.JSONDecodeError:
            continue
    return events


def _stream_chat(
    client: httpx.Client, session_id: str, user_id: str, message: str, *, drop_after_first_text: bool = False
) -> StreamReply:
    reply = StreamReply()
    t0 = time.perf_counter()
    parts: list[str] = []
    with client.stream(
        "POST",
        "/chat/stream",
        json={"message": message, "session_id": session_id, "user_id": user_id},
        timeout=300,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            for event in parse_sse_events([line]):
                if "text" in event:
                    if reply.ttft_ms is None:
                        reply.ttft_ms = int((time.perf_counter() - t0) * 1000)
                    parts.append(event["text"])
                reply.message_id = event.get("message_id", reply.message_id)
                reply.choices = event.get("choices", reply.choices)
                reply.finalizing = reply.finalizing or event.get("event") == "finalizing"
                reply.error = event.get("error", reply.error)
                if "text_replace" in event:
                    parts = [event["text_replace"]]
            if drop_after_first_text and parts:
                break
    reply.text = " ".join(parts)
    reply.latency_ms = int((time.perf_counter() - t0) * 1000)
    return reply


def _accept_suggestions(client: httpx.Client, session_id: str, persona: Persona, result: SessionResult) -> None:
    response = client.post("/context/extract", json={"session_id": session_id}, timeout=180)
    if response.status_code != 200:
        result.errors += 1
        return
    view = response.json()
    to_accept = {
        key: entry["suggestion"]["value"]
        for key, entry in view["fields"].items()
        if entry.get("suggestion") and random.random() < persona.accept_rate
    }
    if to_accept:
        patched = client.patch(
            f"/discovery/{session_id}/rs-field-state",
            json={"action": "accept", "source": "user_accept_suggestion", "fields": to_accept},
        )
        if patched.status_code == 200:
            view = patched.json()
            result.suggestions_accepted += len(to_accept)
    result.discovery_completeness = view.get("discovery_completeness", 0)
    result.accepted_completeness = view.get("accepted_completeness", 0)


def _wait_for_analysis(client: httpx.Client, session_id: str, result: SessionResult) -> None:
    t0 = time.monotonic()
    deadline = t0 + float(os.getenv("SIM_ANALYSIS_TIMEOUT_S", "900"))
    while time.monotonic() < deadline:
        status = client.get(f"/analyses/{session_id}").json().get("status", "not_found")
        result.analysis_status = status
        if status in {"complete", "error"}:
            result.time_to_analysis_s = round(time.monotonic() - t0, 1)
            return
        time.sleep(5)


def _download_docx(client: httpx.Client, session_id: str, user_id: str, result: SessionResult) -> None:
    response = client.post(
        "/document/rs-template/docx", json={"session_id": session_id, "user_id": user_id}, timeout=180
    )
    result.converted = response.status_code == 200


def simulate_session(client: httpx.Client, user: SimUser, project: str, intent: Intent) -> SessionResult:
    persona = user.persona
    session_id = f"sim-{uuid.uuid4()}"
    result = SessionResult(
        session_id=session_id,
        user_id=user.user_id,
        persona=persona.name,
        department=user.department,
        lang=persona.lang,
        project=project,
        intended_outcome=intent,
        started_at=datetime.now(UTC).isoformat(),
    )
    model = PersonaModel(persona, user.department, project)
    quit_after = random.randint(2, 6) if intent == "early_exit" else None
    disconnect_at = random.randint(1, 8) if intent == "disconnect" else None
    history: list[tuple[str, str]] = []
    choices: list[str] = []
    last_message_id = ""
    t0 = time.monotonic()

    while result.user_turns < persona.max_turns:
        turn = model.next_turn(history, choices)
        result.sentiment[turn.sentiment] += 1
        if last_message_id and turn.vote_on_last_reply != "none":
            voted = client.post(
                "/feedback",
                json={"session_id": session_id, "message_id": last_message_id, "vote": turn.vote_on_last_reply},
            )
            if voted.status_code == 200:
                result.thumbs_up += turn.vote_on_last_reply == "up"
                result.thumbs_down += turn.vote_on_last_reply == "down"
        if turn.quit or result.user_turns == quit_after:
            result.outcome = "abandoned"
            break

        result.user_turns += 1
        result.user_chars += len(turn.message)
        history.append(("User", turn.message))
        dropping = result.user_turns == disconnect_at
        try:
            reply = _stream_chat(client, session_id, user.user_id, turn.message, drop_after_first_text=dropping)
        except httpx.HTTPError as exc:
            logger.warning(f"Simulated turn failed: session_id={session_id} error={exc}")
            result.errors += 1
            result.outcome = "error"
            break
        if dropping:
            result.outcome = "disconnected"
            break
        if reply.error:
            result.errors += 1
            result.outcome = "error"
            break

        history.append(("Consultant", reply.text))
        result.assistant_chars += len(reply.text)
        result.latency_ms.append(reply.latency_ms)
        if reply.ttft_ms is not None:
            result.ttft_ms.append(reply.ttft_ms)
        choices = reply.choices
        result.choices_shown += bool(choices)
        last_message_id = reply.message_id
        _accept_suggestions(client, session_id, persona, result)

        if reply.finalizing:
            result.finalized = True
            result.outcome = "completed"
            _wait_for_analysis(client, session_id, result)
            _download_docx(client, session_id, user.user_id, result)
            break

    result.duration_s = round(time.monotonic() - t0, 1)
    # A user who closed the tab never sees the rating dialog.
    if history and result.outcome != "disconnected":
        verdict = model.verdict(history)
        result.rating = verdict.rating
        result.rating_comment = verdict.comment
        result.goal_achieved = verdict.goal_achieved
        result.stayed_business_focused = verdict.stayed_business_focused
        client.post(
            "/feedback/session",
            json={"session_id": session_id, "rating": verdict.rating, "comment": verdict.comment},
        )
    return result


def _use_gcs() -> bool:
    return bool(os.getenv("GCS_BUCKET_NAME"))


def _local_dir() -> Path:
    return Path(os.getenv("SIM_RESULTS_DIR", "sim_results"))


def load_results(local_dir: Path | None = None) -> list[dict]:
    if local_dir is None and _use_gcs():
        from gcs.connector import list_files, read_text

        return [json.loads(read_text(name)) for name in list_files(RESULTS_PREFIX) if name.endswith(".json")]
    directory = local_dir or _local_dir()
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("sim-*.json"))]


def _save_result(result: SessionResult) -> str:
    payload = json.dumps(asdict(result), ensure_ascii=False, indent=2)
    if _use_gcs():
        from gcs.connector import write_file

        return write_file(f"{RESULTS_PREFIX}{result.session_id}.json", payload, content_type="application/json")
    out_dir = _local_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.session_id}.json"
    path.write_text(payload, encoding="utf-8")
    return str(path)


def pick_user_and_project(past: list[dict]) -> tuple[SimUser, str]:
    churned = {r["user_id"] for r in past if r.get("rating") is not None and r["rating"] <= CHURN_RATING}
    active = [u for u in USERS if u.user_id not in churned] or USERS
    user = random.choice(active)
    done = {r["project"] for r in past if r["user_id"] == user.user_id}
    projects = [p for p in PROJECTS[user.department] if p not in done] or PROJECTS[user.department]
    return user, random.choice(projects)


def run() -> int:
    from logger import setup_logging

    setup_logging()
    target = os.getenv("SIM_TARGET_URL", "").rstrip("/")
    if not target:
        logger.error("SIM_TARGET_URL is required, e.g. https://backend-xyz.run.app")
        return 2

    # Hourly trigger × run probability gives a random number of chats per day.
    if random.random() > float(os.getenv("SIM_RUN_PROBABILITY", "1.0")):
        logger.info("Simulation run skipped this slot: event=rs.sim.skipped")
        return 0
    time.sleep(random.uniform(0, float(os.getenv("SIM_MAX_START_DELAY_S", "0"))))

    headers = {}
    bearer = os.getenv("SIM_AUTH_BEARER", "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    mix = parse_intent_mix(os.getenv("SIM_INTENT_MIX", "finish:0.8,early_exit:0.15,disconnect:0.05"))
    sessions = int(os.getenv("SIM_SESSIONS_PER_RUN", "1"))
    with httpx.Client(base_url=target, headers=headers, timeout=60) as client:
        for _ in range(sessions):
            user, project = pick_user_and_project(load_results())
            intent = random.choices(list(mix), weights=list(mix.values()))[0]
            result = simulate_session(client, user, project, cast(Intent, intent))
            location = _save_result(result)
            logger.info(
                "Simulated session complete: event=rs.sim.session "
                f"session_id={result.session_id} user_id={user.user_id} intent={intent} "
                f"outcome={result.outcome} turns={result.user_turns} rating={result.rating} saved={location}"
            )
    return 0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 1) if values else 0.0


def _p95(values: list[float]) -> float:
    return round(statistics.quantiles(values, n=20)[-1], 1) if len(values) >= 2 else _mean(values)


def _resolved(r: dict) -> bool:
    return r["outcome"] == "completed" and r["analysis_status"] == "complete"


def summarize(results: list[dict]) -> dict:
    n = len(results)
    completed = [r for r in results if r["outcome"] == "completed"]
    finish_intent = [r for r in results if r["intended_outcome"] == "finish"]
    rated = [r["rating"] for r in results if r["rating"] is not None]
    # Disconnected users never see the verdict dialog, so judge only sessions that got one.
    goals = [r["goal_achieved"] for r in results if r["goal_achieved"] is not None]
    focus = [r["stayed_business_focused"] for r in results if r["stayed_business_focused"] is not None]
    votes_up = sum(r["thumbs_up"] for r in results)
    votes = votes_up + sum(r["thumbs_down"] for r in results)
    sentiment: Counter[str] = Counter()
    for r in results:
        sentiment.update(r["sentiment"])
    sessions_by_user = Counter(r["user_id"] for r in results)
    all_ttft = [v for r in results for v in r["ttft_ms"]]
    all_latency = [v for r in results for v in r["latency_ms"]]
    return {
        "sessions": n,
        "intent_shares": {k: _rate(v, n) for k, v in Counter(r["intended_outcome"] for r in results).items()},
        "resolution_rate_finish_intent": _rate(sum(_resolved(r) for r in finish_intent), len(finish_intent)),
        "resolution_rate_all": _rate(sum(_resolved(r) for r in results), n),
        "dropout_rate": _rate(sum(r["outcome"] in {"abandoned", "disconnected"} for r in results), n),
        "error_rate": _rate(sum(r["outcome"] == "error" for r in results), n),
        "turn_cap_rate": _rate(sum(r["outcome"] == "turn_cap" for r in results), n),
        "conversion_rate": _rate(sum(r["converted"] for r in results), n),
        "total_users": len(sessions_by_user),
        "sessions_per_user": _rate(n, len(sessions_by_user)),
        "retention_rate": _rate(sum(c >= 2 for c in sessions_by_user.values()), len(sessions_by_user)),
        "mean_messages_per_session": _mean([r["user_turns"] * 2 for r in results]),
        "mean_turns_to_completion": _mean([r["user_turns"] for r in completed]),
        "mean_duration_min": _mean([r["duration_s"] / 60 for r in results]),
        "median_duration_min_completed": round(statistics.median([r["duration_s"] for r in completed]) / 60, 1)
        if completed
        else 0.0,
        "mean_time_to_analysis_s": _mean([r["time_to_analysis_s"] for r in completed if r["time_to_analysis_s"]]),
        "csat_mean": _mean(rated),
        "csat_pct_4_or_5": _rate(sum(v >= 4 for v in rated), len(rated)),
        "rating_distribution": {str(k): rated.count(k) for k in range(1, 6)},
        "thumbs_up_ratio": _rate(votes_up, votes),
        "sentiment_shares": {
            k: _rate(sentiment[k], sum(sentiment.values())) for k in ("positive", "neutral", "negative")
        },
        "goal_achieved_rate": _rate(sum(goals), len(goals)),
        "business_focus_rate": _rate(sum(focus), len(focus)),
        "mean_accepted_completeness": _mean([r["accepted_completeness"] for r in results]),
        "mean_discovery_completeness": _mean([r["discovery_completeness"] for r in results]),
        "mean_ttft_ms": _mean(all_ttft),
        "p95_latency_ms": _p95(all_latency),
    }


def report(results_dir: str) -> int:
    directory = Path(results_dir)
    results = load_results(directory)
    if not results:
        print(f"No results in {results_dir}")
        return 1

    with (directory / "sessions.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    personas = sorted({r["persona"] for r in results})
    summary = {
        "overall": summarize(results),
        "by_persona": {name: summarize([r for r in results if r["persona"] == name]) for name in personas},
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "report":
        raise SystemExit(report(sys.argv[2] if len(sys.argv) > 2 else "sim_results"))
    raise SystemExit(run())


if __name__ == "__main__":
    main()
