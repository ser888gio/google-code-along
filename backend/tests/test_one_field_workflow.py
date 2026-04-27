from agent.discovery_agent import (
    initialize_workflow_state,
    pick_next_active_field,
    sync_workflow_with_discovery_state,
)
from answer_classifier import (
    clean_direct_answer_value,
    is_deferred_answer,
    is_short_clarification_question,
    mentions_other_direct_field,
)
from direct_field_context import build_augmented_user_message


def test_pick_next_active_field_prioritizes_required_schema_order():
    state = initialize_workflow_state()
    state["field_status"]["use_case_title"] = "answered"
    state["field_status"]["department"] = "answered"

    assert pick_next_active_field(state) == "requestor"


def test_pick_next_active_field_returns_none_when_all_fields_resolved():
    state = initialize_workflow_state()
    for key in state["field_status"]:
        state["field_status"][key] = "answered"

    assert pick_next_active_field(state) is None


def test_sync_workflow_marks_discovery_and_deferred_fields():
    state = initialize_workflow_state()
    synced = sync_workflow_with_discovery_state(
        state,
        {
            "fields": {
                "department": {"filled": True, "value": "HR"},
                "requestor": {"filled": False, "value": None},
            }
        },
        {},
        {"product_owner": {"deferred_at": "now"}},
    )

    assert synced["field_status"]["department"] == "answered"
    assert synced["field_status"]["product_owner"] == "deferred"
    assert synced["field_status"]["requestor"] == "missing"


def test_deferred_answer_detection_is_czech_and_diacritic_insensitive():
    assert is_deferred_answer("Nevim, doplnim pozdeji.")
    assert is_deferred_answer("Netusim")
    assert is_deferred_answer("Zjistím později")
    assert is_deferred_answer("I don't know")


def test_direct_answer_cleaning_and_clarification_heuristic():
    assert clean_direct_answer_value("Je to HR.") == "HR"
    assert is_short_clarification_question("Co tim myslite?")
    assert not is_short_clarification_question("Je to pro HR?")


def test_direct_fast_path_detects_proactive_other_field_mentions():
    assert mentions_other_direct_field(
        "department", "Je to pro HR a requestor je Jan Novak"
    )
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
