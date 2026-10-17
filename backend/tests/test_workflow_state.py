import pytest
from field_schema import FIELD_SCHEMA
from workflow_state import (
    FieldStatus,
    InvalidTransition,
    Phase,
    WorkflowEvent,
    WorkflowState,
)

_first_field = next(iter(FIELD_SCHEMA))

# ---------------------------------------------------------------------------
# All 11 valid transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS = [
    (Phase.DISCOVERY, WorkflowEvent.FIELD_FOUND, Phase.DISCOVERY),
    (Phase.DISCOVERY, WorkflowEvent.FIELDS_EXHAUSTED, Phase.WRAP_UP),
    (Phase.DISCOVERY, WorkflowEvent.FINISH_REQUESTED, Phase.WRAP_UP),
    (Phase.WRAP_UP, WorkflowEvent.FINALIZE_CHOSEN, Phase.READY_TO_FINALIZE),
    (Phase.WRAP_UP, WorkflowEvent.REOPEN_DEFERRED, Phase.DISCOVERY),
    (Phase.WRAP_UP, WorkflowEvent.FIELD_FOUND, Phase.DISCOVERY),
    (Phase.WRAP_UP, WorkflowEvent.FIELDS_EXHAUSTED, Phase.WRAP_UP),
    (Phase.READY_TO_FINALIZE, WorkflowEvent.FINALIZE_STARTED, Phase.FINALIZING),
    (Phase.FINALIZING, WorkflowEvent.FINALIZE_COMPLETE, Phase.COMPLETE),
    (Phase.FINALIZING, WorkflowEvent.FINALIZE_FAILED, Phase.FAILED),
    (Phase.FAILED, WorkflowEvent.FINALIZE_RETRY, Phase.WRAP_UP),
]


@pytest.mark.parametrize("start_phase,event,expected_phase", _VALID_TRANSITIONS)
def test_valid_transition_reaches_expected_phase(start_phase, event, expected_phase):
    state = WorkflowState()
    state.phase = start_phase
    state.transition(event, active_field=_first_field)
    assert state.phase == expected_phase


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

_INVALID_TRANSITIONS = [
    (Phase.DISCOVERY, WorkflowEvent.FINALIZE_COMPLETE),
    (Phase.DISCOVERY, WorkflowEvent.FINALIZE_STARTED),
    (Phase.DISCOVERY, WorkflowEvent.FINALIZE_CHOSEN),
    (Phase.DISCOVERY, WorkflowEvent.FINALIZE_FAILED),
    (Phase.COMPLETE, WorkflowEvent.FIELD_FOUND),
    (Phase.COMPLETE, WorkflowEvent.FINALIZE_RETRY),
    (Phase.WRAP_UP, WorkflowEvent.FINALIZE_STARTED),
    (Phase.WRAP_UP, WorkflowEvent.FINISH_REQUESTED),
    (Phase.READY_TO_FINALIZE, WorkflowEvent.FINALIZE_CHOSEN),
    (Phase.FAILED, WorkflowEvent.FIELD_FOUND),
]


@pytest.mark.parametrize("start_phase,event", _INVALID_TRANSITIONS)
def test_invalid_transition_raises(start_phase, event):
    state = WorkflowState()
    state.phase = start_phase
    with pytest.raises(InvalidTransition):
        state.transition(event)


# ---------------------------------------------------------------------------
# Payload side effects
# ---------------------------------------------------------------------------


def test_field_found_sets_active_field():
    state = WorkflowState()
    state.transition(WorkflowEvent.FIELD_FOUND, active_field=_first_field)
    assert state.active_field == _first_field


def test_finalize_chosen_clears_active_field():
    state = WorkflowState()
    state.phase = Phase.WRAP_UP
    state.active_field = _first_field
    state.transition(WorkflowEvent.FINALIZE_CHOSEN)
    assert state.active_field is None


def test_fields_exhausted_clears_active_field():
    state = WorkflowState()
    state.active_field = _first_field
    state.transition(WorkflowEvent.FIELDS_EXHAUSTED)
    assert state.active_field is None


def test_reopen_deferred_sets_active_field_resets_status_and_miss_count():
    state = WorkflowState()
    state.phase = Phase.WRAP_UP
    state.field_status[_first_field] = FieldStatus.DEFERRED
    state.miss_counts[_first_field] = 5
    state.transition(WorkflowEvent.REOPEN_DEFERRED, active_field=_first_field)
    assert state.active_field == _first_field
    assert state.field_status[_first_field] == FieldStatus.MISSING
    assert state.miss_counts[_first_field] == 0


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_round_trip():
    state = WorkflowState()
    state.phase = Phase.WRAP_UP
    state.active_field = _first_field
    state.field_status[_first_field] = FieldStatus.ANSWERED
    state.miss_counts[_first_field] = 2
    state.clarification_counts[_first_field] = 1
    state.coverage_gaps[_first_field] = ["gap_a", "gap_b"]

    restored = WorkflowState.from_dict(state.to_dict())

    assert restored.phase == Phase.WRAP_UP
    assert restored.active_field == _first_field
    assert restored.field_status[_first_field] == FieldStatus.ANSWERED
    assert restored.miss_counts[_first_field] == 2
    assert restored.clarification_counts[_first_field] == 1
    assert restored.coverage_gaps[_first_field] == ["gap_a", "gap_b"]


# ---------------------------------------------------------------------------
# from_dict robustness
# ---------------------------------------------------------------------------


def test_from_dict_none_returns_defaults():
    state = WorkflowState.from_dict(None)
    assert state.phase == Phase.DISCOVERY
    assert state.active_field is None


def test_from_dict_unknown_phase_falls_back_to_discovery():
    state = WorkflowState.from_dict({"phase": "totally_unknown_xyz"})
    assert state.phase == Phase.DISCOVERY


def test_from_dict_active_field_not_in_schema_becomes_none():
    state = WorkflowState.from_dict({"phase": "discovery", "active_field": "__not_a_real_field__"})
    assert state.active_field is None


def test_from_dict_unknown_field_status_becomes_missing():
    state = WorkflowState.from_dict(
        {
            "phase": "discovery",
            "field_status": {_first_field: "totally_unknown_status"},
        }
    )
    assert state.field_status[_first_field] == FieldStatus.MISSING
