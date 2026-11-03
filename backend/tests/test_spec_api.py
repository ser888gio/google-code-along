"""HTTP surface of the section state machine, with Firestore and the LLM stubbed."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from api import spec as spec_api
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spec_machine import store as store_module
from spec_machine.model import GenerateOutput, GenerateRequest, ProposalOutput, SectionConfig, SectionEvent
from spec_machine.services import build_services

from tests.fake_firestore import FakeFirestore, fake_transactional


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(store_module.firestore, "transactional", fake_transactional, raising=False)
    db = FakeFirestore()
    monkeypatch.setattr("spec_machine.services._client", lambda: cast(Any, db))
    llm_calls: list[GenerateRequest] = []

    async def generate(request: GenerateRequest, abort: asyncio.Event) -> GenerateOutput:
        llm_calls.append(request)
        return ProposalOutput("Patents reporting", "short and specific")

    async def no_model(text: str, config: SectionConfig) -> SectionEvent | None:
        return None

    monkeypatch.setattr(spec_api, "build_services", lambda sid: build_services(sid).provide(generate=generate))
    monkeypatch.setattr(spec_api, "intent_classifier", lambda sid: no_model)
    spec_api._documents.clear()
    app = FastAPI()
    app.include_router(spec_api.router)
    test_client = TestClient(app)
    test_client.llm_calls = llm_calls  # type: ignore[attr-defined]
    return test_client


def test_utterance_and_events_drive_the_current_section(client: TestClient) -> None:
    snapshot = client.get("/spec/s1").json()["snapshot"]
    assert snapshot["cursor"] == "use_case_title"
    assert snapshot["current"]["state"] == "gathering"

    body = client.post("/spec/s1/utterance", json={"text": "we track patents monthly"}).json()
    assert body["events"] == ["UserMessage"]
    assert body["snapshot"]["current"]["state"] == "proposed"
    assert body["snapshot"]["current"]["proposal"] == "Patents reporting"

    body = client.post("/spec/s1/utterance", json={"text": "looks good", "modality": "voice"}).json()
    assert body["events"] == ["Accept"]
    assert body["snapshot"]["current"]["state"] == "accepted"
    assert body["snapshot"]["current"]["value"] == "Patents reporting"

    body = client.post("/spec/s1/events", json={"type": "NEXT"}).json()
    assert body["handled"] is True
    assert body["snapshot"]["cursor"] == "department"


def test_simple_field_voice_answer_is_read_back(client: TestClient) -> None:
    client.post("/spec/s1/events", json={"type": "GO_TO", "section_id": "product_owner"})
    body = client.post("/spec/s1/utterance", json={"text": "Petr Novák", "modality": "voice"}).json()
    assert body["snapshot"]["current"]["state"] == "confirming"
    body = client.post("/spec/s1/utterance", json={"text": "yes", "modality": "voice"}).json()
    assert body["snapshot"]["current"]["state"] == "accepted"
    assert client.llm_calls == []  # type: ignore[attr-defined]


def test_bad_requests(client: TestClient) -> None:
    assert client.get("/spec/bad..id").status_code == 400
    assert client.post("/spec/s1/events", json={"type": "SUBMIT"}).status_code == 422
    assert client.post("/spec/s1/events", json={"type": "NOPE"}).status_code == 422
