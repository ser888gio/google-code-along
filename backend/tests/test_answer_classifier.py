import asyncio
import json
from unittest.mock import MagicMock, patch

from answer_classifier import classify_user_turn


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
