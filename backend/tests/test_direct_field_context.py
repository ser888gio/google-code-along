from direct_field_context import (
    build_augmented_user_message,
    clean_direct_fields,
    merge_direct_fields,
)


def test_clean_direct_fields_keeps_known_non_empty_values():
    result = clean_direct_fields(
        {
            "product_owner": "  Jana Novak  ",
            "unknown": "ignored",
            "department": "",
            "requestor": None,
        }
    )

    assert result == {"product_owner": "Jana Novak"}


def test_merge_direct_fields_prefers_incoming_values():
    result = merge_direct_fields(
        {"product_owner": "Old Owner", "department": "Sales"},
        {"product_owner": "New Owner"},
    )

    assert result == {
        "department": "Sales",
        "product_owner": "New Owner",
    }


def test_merge_direct_fields_allows_incoming_empty_value_to_clear_stored_value():
    result = merge_direct_fields(
        {"product_owner": "Old Owner", "department": "Sales"},
        {"product_owner": ""},
    )

    assert result == {"department": "Sales"}


def test_augmented_user_message_tells_agent_not_to_reask_direct_fields():
    result = build_augmented_user_message(
        "Muzeme pokracovat?",
        {"product_owner": "Jana Novak"},
    )

    assert "Product Owner: Jana Novak" in result
    assert "do not ask for them again" in result
    assert result.endswith("User message:\nMuzeme pokracovat?")


def test_augmented_user_message_is_unchanged_without_direct_fields():
    assert build_augmented_user_message("Hello", {}) == "Hello"
