import json

from field_schema import FIELD_SCHEMA
from scripts.migrate_sections import plan_session
from spec_machine.model import coerce_section


def test_plan_maps_accepted_to_filled_and_dismissed_to_reject_events() -> None:
    legacy = {
        "use_case_title": {
            "accepted": {"value": "Patents reporting", "source": "user_manual"},
            "dismissed_suggestions": ["Reporting"],
        },
        "department": {"dismissed_suggestions": ["HR", "IT"]},
        "bogus_key": {"accepted": {"value": "x"}},
    }
    plan = plan_session("s1", {"rs_field_state_json": json.dumps(legacy)}, existing=["requester"])

    assert set(plan.sections) == set(FIELD_SCHEMA) - {"requester"}
    assert plan.sections["use_case_title"]["status"] == "filled"
    assert plan.sections["use_case_title"]["value"] == "Patents reporting"
    assert plan.sections["department"]["status"] == "empty"
    assert all(coerce_section(dict(s)) == s for s in plan.sections.values())
    assert [(e["field_key"], e["after"]) for e in plan.events] == [
        ("use_case_title", "Reporting"),
        ("department", "HR"),
        ("department", "IT"),
    ]


def test_plan_tolerates_missing_or_corrupt_legacy_state() -> None:
    assert all(s["status"] == "empty" for s in plan_session("s1", {}, []).sections.values())
    assert all(
        s["status"] == "empty" for s in plan_session("s1", {"rs_field_state_json": "{not json"}, []).sections.values()
    )
