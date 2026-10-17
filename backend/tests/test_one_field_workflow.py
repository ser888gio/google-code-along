from agent.discovery_agent import (
    pick_next_active_field,
    sync_workflow_with_discovery_state,
)
from answer_classifier import (
    clean_direct_answer_value,
    is_deferred_answer,
    mentions_other_direct_field,
)
from direct_field_context import build_augmented_user_message
from workflow_state import WorkflowState


def test_pick_next_active_field_prioritizes_required_schema_order():
    state = WorkflowState()
    state.field_status["use_case_title"] = "answered"
    state.field_status["department"] = "answered"

    assert pick_next_active_field(state) == "requester"


def test_pick_next_active_field_returns_none_when_all_fields_resolved():
    state = WorkflowState()
    for key in state.field_status:
        state.field_status[key] = "answered"

    assert pick_next_active_field(state) is None


def test_sync_workflow_marks_discovery_and_deferred_fields():
    state = WorkflowState()
    synced = sync_workflow_with_discovery_state(
        state,
        {
            "fields": {
                "department": {"filled": True, "value": "HR"},
                "requester": {"filled": False, "value": None},
            }
        },
        {},
        {"product_owner": {"deferred_at": "now"}},
    )

    assert synced.field_status["department"] == "answered"
    assert synced.field_status["product_owner"] == "deferred"
    assert synced.field_status["requester"] == "missing"


def test_deferred_answer_detection_is_czech_and_diacritic_insensitive():
    assert is_deferred_answer("Nevim, doplnim pozdeji.")
    assert is_deferred_answer("Netusim")
    assert is_deferred_answer("Zjistím později")
    assert is_deferred_answer("I don't know")


def test_direct_answer_cleaning():
    assert clean_direct_answer_value("Je to HR.") == "HR"


def test_direct_fast_path_detects_proactive_other_field_mentions():
    assert mentions_other_direct_field("department", "Je to pro HR a requester je Jan Novak")
    assert not mentions_other_direct_field("department", "HR")


def test_workflow_context_renders_active_field_and_wrap_up():
    result = build_augmented_user_message(
        "Co znamena Product Owner?",
        {},
        [],
        workflow_context={
            "phase": "discovery",
            "active_field": "product_owner",
            "clarification_requested": True,
            "answered_fields": {"department": "HR"},
            "deferred_fields": ["saved_time_hours_per_year"],
        },
        field_labels={
            "product_owner": "Product Owner",
            "department": "Customer Department",
            "saved_time_hours_per_year": "Saved Time (hours/year)",
        },
    )

    assert "Active field: Product Owner" in result
    assert "Customer Department: HR" in result
    assert "Saved Time (hours/year)" in result
    assert result.endswith("User message:\nCo znamena Product Owner?")

    wrap_up = build_augmented_user_message(
        "Finalizuj",
        {},
        [],
        workflow_context={
            "phase": "wrap_up",
            "deferred_fields": ["risk_avoidance"],
        },
        field_labels={"risk_avoidance": "Risk Avoidance"},
    )

    assert "Phase: wrap_up" in wrap_up
    assert "Risk Avoidance" in wrap_up
    assert '<choices>["Dokončit s otevřenými otázkami", "Doplnit chybějící údaje"]</choices>' in wrap_up
    assert '<choices>["Finalize with open questions", "Fill in the missing details"]</choices>' in wrap_up


def test_wrap_up_without_deferred_fields_offers_plain_finalize_choices():
    wrap_up = build_augmented_user_message(
        "ok",
        {},
        [],
        workflow_context={"phase": "wrap_up", "deferred_fields": []},
        field_labels={},
    )

    assert "should you finalize the specification now?" in wrap_up
    assert '<choices>["Dokončit specifikaci", "Doplnit další údaje"]</choices>' in wrap_up
    assert '<choices>["Finalize the specification", "Add more details"]</choices>' in wrap_up
