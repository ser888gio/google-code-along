import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_turn import _is_finalize_choice, prepare_workflow_turn, run_turn_postprocessing


def _std_patches(**overrides):
    """Minimal set of patches required by prepare_workflow_turn."""
    defaults = {
        "chat_turn.get_workflow_state": MagicMock(return_value=None),
        "chat_turn.get_discovery_state": MagicMock(return_value=None),
        "chat_turn.get_deferred_fields": MagicMock(return_value={}),
        "chat_turn.upsert_workflow_state": MagicMock(return_value=None),
        "chat_turn.upsert_deferred_fields": MagicMock(return_value=None),
        "chat_turn.remove_deferred_fields": MagicMock(return_value=None),
        "chat_turn.sync_workflow_with_discovery_state": MagicMock(side_effect=lambda state, *a, **kw: state),
        "chat_turn.pick_next_active_field": MagicMock(return_value="use_case_title"),
        "chat_turn.is_not_applicable_allowed": MagicMock(return_value=True),
        "chat_turn.solution_type_value": MagicMock(return_value="generic"),
        "chat_turn.classify_and_update_active_field": AsyncMock(
            return_value=(
                {
                    "classification": "answered",
                    "value": "test_val",
                    "confidence": 0.9,
                    "proactive_fields": {},
                    "coverage_gaps": [],
                },
                None,
            )
        ),
        "chat_turn.apply_proactive_updates": AsyncMock(return_value=None),
    }
    defaults.update(overrides)
    return defaults


def _run_prepare(message="hello", direct_fields=None, incoming_deferred=None, **patch_overrides):
    mocks = _std_patches(**patch_overrides)
    patchers = [patch(target, new=mock) for target, mock in mocks.items()]
    for p in patchers:
        p.start()
    try:
        result = asyncio.run(
            prepare_workflow_turn(
                session_id="sess1",
                message=message,
                incoming_deferred=incoming_deferred,
                session=None,
                direct_fields=direct_fields or {},
            )
        )
    finally:
        for p in patchers:
            p.stop()
    return result, {target: mock for target, mock in mocks.items()}


# ---------------------------------------------------------------------------
# Case 1: wrap-up + finalize choice → ready_to_finalize
# ---------------------------------------------------------------------------


def test_wrap_up_finalize_choice_transitions_to_ready_to_finalize():
    result, _ = _run_prepare(
        message="finalize",
        **{"chat_turn.get_workflow_state": MagicMock(return_value={"phase": "wrap_up"})},
    )
    assert result["workflow"]["phase"] == "ready_to_finalize"


@pytest.mark.parametrize(
    "message",
    [
        "finalize",
        "Yes, finalize it.",
        "Let's finalize with the open questions.",
        "Finalize with open questions",
        "Yes, let's do that.",
        "Go ahead and finish it.",
        "Wrap it up please.",
        "Generate the document.",
        "Ano, prosím.",
        "Ano, souhlasím.",
        "No jasně, dokončete to.",
        "Finalizovat s otevřenými otázkami.",
        "Dokončit s otevřenými otázkami",
        "Vygenerovat specifikaci.",
        "Dokončete to.",
        "Klidně to uzavřete.",
        "Hotovo, můžeme skončit.",
        "Nic dalšího mě již nenapadá.",
        "Doplním to později.",
        "Chci nechat otevřené.",
        # Real simulated-user replies that previously fell through to discovery.
        "Pojďme už rovnou k vygenerování té specifikace.",
        "Tyto otevřené body si vyřešíme interně. Prosím tedy o finální vygenerování specifikace.",
    ],
)
def test_is_finalize_choice_accepts(message):
    assert _is_finalize_choice(message)


@pytest.mark.parametrize(
    "message",
    [
        "I need more time",
        "No, let's fill them in.",
        "Not yet.",
        "Don't finalize yet.",
        "Fill in the missing details",
        "Add more details",
        "Ne, doplním to teď.",
        "Doplnit chybějící údaje",
        "Ano, ale nejdřív doplním rozpočet.",
        "Nechci to nechat otevřené.",
        "Ještě ne.",
        "Rozpočet je 500 000 Kč.",
    ],
)
def test_is_finalize_choice_rejects(message):
    assert not _is_finalize_choice(message)


# ---------------------------------------------------------------------------
# Case 2: wrap-up + non-finalize + deferred fields → discovery, deferred removed
# ---------------------------------------------------------------------------


def test_wrap_up_non_finalize_with_deferred_reopens_first_deferred_field():
    mock_remove = MagicMock(return_value=None)
    result, mocks = _run_prepare(
        message="I need more time",
        **{
            "chat_turn.get_workflow_state": MagicMock(return_value={"phase": "wrap_up"}),
            "chat_turn.get_deferred_fields": MagicMock(
                return_value={"department": {"deferred_at": "2026-06-10T00:00:00Z"}}
            ),
            "chat_turn.remove_deferred_fields": mock_remove,
        },
    )
    assert result["workflow"]["phase"] == "discovery"
    mock_remove.assert_called_once_with("sess1", ["department"])


# ---------------------------------------------------------------------------
# Case 3: discovery with active field → classify and apply called
# ---------------------------------------------------------------------------


def test_discovery_with_active_field_calls_classifier_and_proactive():
    mock_classify = AsyncMock(
        return_value=(
            {
                "classification": "answered",
                "value": "Finance",
                "confidence": 0.95,
                "proactive_fields": {},
                "coverage_gaps": [],
            },
            None,
        )
    )
    mock_apply = AsyncMock(return_value=None)
    _run_prepare(
        message="Finance department",
        **{
            "chat_turn.get_workflow_state": MagicMock(
                return_value={"phase": "discovery", "active_field": "department"}
            ),
            "chat_turn.classify_and_update_active_field": mock_classify,
            "chat_turn.apply_proactive_updates": mock_apply,
        },
    )
    mock_classify.assert_awaited_once()
    mock_apply.assert_awaited_once()


# ---------------------------------------------------------------------------
# Case 4: pick_next_active_field returns None → phase transitions to wrap_up
# ---------------------------------------------------------------------------


def test_all_fields_exhausted_transitions_to_wrap_up():
    result, _ = _run_prepare(
        **{"chat_turn.pick_next_active_field": MagicMock(return_value=None)},
    )
    assert result["workflow"]["phase"] == "wrap_up"


# ---------------------------------------------------------------------------
# Case 5: NOT_APPLICABLE coercion → DEFERRED when disallowed
# ---------------------------------------------------------------------------


def test_not_applicable_coerced_to_deferred_when_disallowed():
    result, _ = _run_prepare(
        **{
            "chat_turn.get_workflow_state": MagicMock(
                return_value={
                    "phase": "discovery",
                    "field_status": {"department": "not_applicable"},
                }
            ),
            "chat_turn.is_not_applicable_allowed": MagicMock(return_value=False),
        },
    )
    assert result["workflow"]["field_status"]["department"] == "deferred"


# ---------------------------------------------------------------------------
# Case 6: upsert_workflow_state called exactly once with session_id
# ---------------------------------------------------------------------------


def test_prepare_workflow_turn_persists_state_once():
    mock_upsert = MagicMock(return_value=None)
    _run_prepare(
        **{"chat_turn.upsert_workflow_state": mock_upsert},
    )
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.args[0] == "sess1"


# ---------------------------------------------------------------------------
# run_turn_postprocessing: non-finalizing path schedules persistence
# ---------------------------------------------------------------------------


def test_run_turn_postprocessing_non_finalizing_schedules_append():
    mock_append = MagicMock(return_value=None)
    with patch("chat_turn.append_conversation_turn", mock_append):
        asyncio.run(
            run_turn_postprocessing(
                session_id="sess1",
                user_id="user1",
                user_text="hello",
                assistant_text="hi there",
                is_finalizing=False,
            )
        )
    mock_append.assert_called_once()
    call_args = mock_append.call_args.args
    assert call_args[0] == "sess1"
    assert call_args[1] == "hello"
    assert call_args[2] == "hi there"
