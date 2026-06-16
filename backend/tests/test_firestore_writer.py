import json
from unittest.mock import MagicMock, patch

from firestore.writer import (
    append_conversation_turn,
    get_final_analysis,
    set_finalization_pending,
    upsert_discovery_state,
    upsert_final_analysis,
)


def _mock_client():
    """Return (mock_client, mock_doc_ref) with collection/document chain wired."""
    doc_ref = MagicMock()
    client = MagicMock()
    client.collection.return_value.document.return_value = doc_ref
    return client, doc_ref


# ---------------------------------------------------------------------------
# set_finalization_pending
# ---------------------------------------------------------------------------


def test_set_finalization_pending_writes_pending_status_with_merge():
    client, doc_ref = _mock_client()
    with patch("firestore.writer._client", return_value=client):
        set_finalization_pending("sess1")

    doc_ref.set.assert_called_once()
    payload = doc_ref.set.call_args.args[0]
    assert payload["finalization_status"] == "pending"
    assert payload["session_id"] == "sess1"
    assert doc_ref.set.call_args.kwargs.get("merge") is True


# ---------------------------------------------------------------------------
# upsert_final_analysis
# ---------------------------------------------------------------------------


def test_upsert_final_analysis_writes_complete_status_and_json():
    client, doc_ref = _mock_client()
    analysis = {"executive_summary": "All good", "score": 42}

    with patch("firestore.writer._client", return_value=client):
        upsert_final_analysis("sess1", analysis)

    doc_ref.set.assert_called_once()
    payload = doc_ref.set.call_args.args[0]
    assert payload["finalization_status"] == "complete"
    assert payload["session_id"] == "sess1"
    stored = json.loads(payload["final_analysis_json"])
    assert stored == analysis
    assert doc_ref.set.call_args.kwargs.get("merge") is True


# ---------------------------------------------------------------------------
# get_final_analysis — four cases
# ---------------------------------------------------------------------------


def _snap_mock(exists=True, data=None):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def test_get_final_analysis_returns_none_when_doc_does_not_exist():
    client, doc_ref = _mock_client()
    doc_ref.get.return_value = _snap_mock(exists=False)

    with patch("firestore.writer._client", return_value=client):
        result = get_final_analysis("sess1")

    assert result is None


def test_get_final_analysis_returns_pending_dict_when_status_pending():
    client, doc_ref = _mock_client()
    doc_ref.get.return_value = _snap_mock(data={"finalization_status": "pending"})

    with patch("firestore.writer._client", return_value=client):
        result = get_final_analysis("sess1")

    assert result == {"finalization_status": "pending"}


def test_get_final_analysis_parses_json_when_status_complete():
    client, doc_ref = _mock_client()
    analysis_body = {"executive_summary": "Done", "score": 99}
    doc_ref.get.return_value = _snap_mock(
        data={
            "finalization_status": "complete",
            "final_analysis_json": json.dumps(analysis_body),
        }
    )

    with patch("firestore.writer._client", return_value=client):
        result = get_final_analysis("sess1")

    assert result is not None
    assert result["finalization_status"] == "complete"
    assert result["executive_summary"] == "Done"
    assert result["score"] == 99


def test_get_final_analysis_returns_raw_data_when_json_is_corrupt():
    raw_data = {"finalization_status": "complete", "final_analysis_json": "{{not valid json"}
    client, doc_ref = _mock_client()
    doc_ref.get.return_value = _snap_mock(data=raw_data)

    with patch("firestore.writer._client", return_value=client):
        result = get_final_analysis("sess1")

    assert result is not None
    assert result["finalization_status"] == "complete"


# ---------------------------------------------------------------------------
# upsert_discovery_state
# ---------------------------------------------------------------------------


def test_upsert_discovery_state_stores_json_with_merge():
    client, doc_ref = _mock_client()
    discovery = {"completeness": 75, "fields": {"department": {"filled": True, "value": "HR"}}}

    with patch("firestore.writer._client", return_value=client):
        upsert_discovery_state("sess1", discovery)

    doc_ref.set.assert_called_once()
    payload = doc_ref.set.call_args.args[0]
    assert payload["session_id"] == "sess1"
    stored = json.loads(payload["discovery_state_json"])
    assert stored == discovery
    assert doc_ref.set.call_args.kwargs.get("merge") is True


# ---------------------------------------------------------------------------
# append_conversation_turn
# ---------------------------------------------------------------------------


def test_append_conversation_turn_calls_set_with_merge_and_session_id():
    client, doc_ref = _mock_client()

    with patch("firestore.writer._client", return_value=client):
        append_conversation_turn("sess1", "user message", "assistant reply")

    doc_ref.set.assert_called_once()
    payload = doc_ref.set.call_args.args[0]
    assert payload["session_id"] == "sess1"
    assert "messages" in payload
    assert doc_ref.set.call_args.kwargs.get("merge") is True
