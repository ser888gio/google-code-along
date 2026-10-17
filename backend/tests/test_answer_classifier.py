import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from answer_classifier import classify_user_turn, classify_wrap_up_reply


def _model_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=json.dumps(payload))
    return client


def _classifier_payload(classification: str, *, finish_requested: bool) -> dict:
    return {
        "active_field_result": {
            "classification": classification,
            "value": None,
            "confidence": 0.9,
            "coverage_gaps": [],
        },
        "proactive_fields": {},
        "finish_requested": finish_requested,
    }


def test_short_question_reaches_the_model_and_reports_finish_request():
    client = _model_client(_classifier_payload("not_answered", finish_requested=True))
    with patch("google.genai.Client", return_value=client):
        result = asyncio.run(classify_user_turn("risk_avoidance", "Můžeme už skončit?"))

    client.models.generate_content.assert_called_once()
    assert result["finish_requested"] is True


def test_deferral_phrase_reaches_the_model():
    client = _model_client(_classifier_payload("deferred", finish_requested=False))
    with patch("google.genai.Client", return_value=client):
        result = asyncio.run(classify_user_turn("risk_avoidance", "To doplním později."))

    client.models.generate_content.assert_called_once()
    assert result["classification"] == "deferred"
    assert result["finish_requested"] is False


def test_model_failure_falls_back_without_finish_request():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("model unavailable")
    with patch("google.genai.Client", return_value=client):
        result = asyncio.run(classify_user_turn("risk_avoidance", "Stačí, vygenerujte to."))

    assert result["classification"] == "not_answered"
    assert not result.get("finish_requested")


@pytest.mark.parametrize(
    "choice,expected",
    [
        ("Dokončit s otevřenými otázkami", "finalize"),
        ("Doplnit chybějící údaje", "fill_in"),
        ("Finalize the specification", "finalize"),
        ("Add more details", "fill_in"),
    ],
)
def test_wrap_up_button_texts_are_decided_without_the_model(choice, expected):
    client = MagicMock()
    with patch("google.genai.Client", return_value=client):
        assert asyncio.run(classify_wrap_up_reply(choice)) == expected
    client.models.generate_content.assert_not_called()


@pytest.mark.parametrize("decision", ["finalize", "fill_in", "unclear"])
def test_wrap_up_free_text_uses_the_model_decision(decision):
    client = _model_client({"decision": decision})
    with patch("google.genai.Client", return_value=client):
        assert asyncio.run(classify_wrap_up_reply("Prosím tedy o finální vygenerování.")) == decision
    client.models.generate_content.assert_called_once()


def test_wrap_up_unknown_model_decision_is_unclear():
    client = _model_client({"decision": "maybe"})
    with patch("google.genai.Client", return_value=client):
        assert asyncio.run(classify_wrap_up_reply("Hmm.")) == "unclear"


def test_wrap_up_model_failure_returns_none_for_fallback():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("model unavailable")
    with patch("google.genai.Client", return_value=client):
        assert asyncio.run(classify_wrap_up_reply("Ano, prosím.")) is None
