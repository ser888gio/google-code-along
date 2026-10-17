from dataclasses import asdict

from observability.simulation.run_simulation import (
    PROJECTS,
    USERS,
    SessionResult,
    parse_intent_mix,
    parse_sse_events,
    pick_user_and_project,
    summarize,
)


def _result(outcome: str, rating: int | None, turns: int, **overrides) -> dict:
    result = SessionResult(
        session_id="sim-x",
        user_id="sim-u01",
        persona="p",
        department="hr",
        lang="en",
        project="x",
        intended_outcome="finish",
        started_at="t",
    )
    result.outcome = outcome
    result.rating = rating
    result.user_turns = turns
    for key, value in overrides.items():
        setattr(result, key, value)
    return asdict(result)


def test_parse_sse_events_skips_keepalive_done_and_garbage():
    lines = [": keepalive", 'data: {"text": "Hi"}', "data: not-json", "data: [DONE]", ""]
    assert parse_sse_events(lines) == [{"text": "Hi"}]


def test_parse_intent_mix():
    assert parse_intent_mix("finish:0.8, early_exit:0.15,disconnect:0.05") == {
        "finish": 0.8,
        "early_exit": 0.15,
        "disconnect": 0.05,
    }


def test_summarize_computes_satisfaction_and_completion_metrics():
    results = [
        _result("completed", 5, 10, thumbs_up=3, duration_s=600, analysis_status="complete", converted=True),
        _result("completed", 4, 20, thumbs_down=1, duration_s=1200, analysis_status="error", user_id="sim-u02"),
        _result("abandoned", 2, 4, intended_outcome="early_exit", user_id="sim-u03"),
        _result("disconnected", None, 1, intended_outcome="disconnect", user_id="sim-u03"),
    ]

    summary = summarize(results)

    assert summary["resolution_rate_finish_intent"] == 0.5
    assert summary["dropout_rate"] == 0.5
    assert summary["conversion_rate"] == 0.25
    assert summary["mean_turns_to_completion"] == 15
    assert summary["median_duration_min_completed"] == 15
    assert summary["csat_mean"] == 3.7
    assert summary["csat_pct_4_or_5"] == 0.667
    assert summary["thumbs_up_ratio"] == 0.75
    assert summary["rating_distribution"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 1}
    assert summary["total_users"] == 3
    assert summary["sessions_per_user"] == 1.333
    assert summary["retention_rate"] == 0.333
    assert summary["intent_shares"] == {"finish": 0.5, "early_exit": 0.25, "disconnect": 0.25}


def test_user_pool_is_stable_and_churned_users_do_not_return():
    assert len(USERS) == 40
    assert len({u.user_id for u in USERS}) == 40

    churned = [{"user_id": u.user_id, "rating": 1, "project": "x"} for u in USERS[:39]]
    user, project = pick_user_and_project(churned)

    assert user == USERS[39]
    assert project in PROJECTS[user.department]
