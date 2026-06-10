from firestore import compose_rs_field_view


def test_compose_rs_field_view_keeps_accepted_value_and_separate_ai_suggestion():
    discovery_state = {
        "completeness": 40,
        "fields": {
            "use_case_title": {"filled": True, "value": "AI Suggested Title", "source": "ai"},
        },
    }
    rs_field_state = {
        "use_case_title": {
            "accepted": {
                "value": "User Confirmed Title",
                "source": "user_manual",
                "accepted_at": "2026-06-10T10:00:00+00:00",
            }
        }
    }

    result = compose_rs_field_view(discovery_state, rs_field_state)

    assert result["completeness"] == result["accepted_completeness"]
    assert result["discovery_completeness"] == 40
    assert result["fields"]["use_case_title"] == {
        "status": "accepted_with_suggestion",
        "accepted": {
            "value": "User Confirmed Title",
            "source": "user_manual",
            "accepted_at": "2026-06-10T10:00:00+00:00",
        },
        "suggestion": {"value": "AI Suggested Title", "source": "ai"},
        "dismissed_suggestions": [],
        "filled": True,
        "value": "User Confirmed Title",
        "source": "user_manual",
    }


def test_compose_rs_field_view_hides_dismissed_or_duplicate_suggestions():
    discovery_state = {
        "completeness": 25,
        "fields": {
            "product_owner": {"filled": True, "value": "Jana Novak", "source": "ai"},
            "department": {"filled": True, "value": "Finance", "source": "ai"},
        },
    }
    rs_field_state = {
        "product_owner": {
            "dismissed_suggestions": ["  jana   novak  "],
        },
        "department": {
            "accepted": {
                "value": "Finance",
                "source": "user_direct_chat",
                "accepted_at": "2026-06-10T10:00:00+00:00",
            }
        },
    }

    result = compose_rs_field_view(discovery_state, rs_field_state)

    assert result["fields"]["product_owner"]["status"] == "empty"
    assert result["fields"]["product_owner"]["suggestion"] is None
    assert result["fields"]["product_owner"]["dismissed_suggestions"] == ["  jana   novak  "]

    assert result["fields"]["department"]["status"] == "accepted"
    assert result["fields"]["department"]["accepted"]["value"] == "Finance"
    assert result["fields"]["department"]["suggestion"] is None
