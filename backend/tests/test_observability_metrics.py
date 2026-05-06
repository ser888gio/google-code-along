from observability import metrics


class _FakeCounter:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes=None):
        self.calls.append((value, attributes or {}))


class _FakeHistogram:
    def __init__(self):
        self.calls = []

    def record(self, value, attributes=None):
        self.calls.append((value, attributes or {}))


def test_phase6_session_metrics_include_outcome(monkeypatch):
    counter = _FakeCounter()
    histogram = _FakeHistogram()
    monkeypatch.setattr(metrics, "session_completion_counter", counter)
    monkeypatch.setattr(metrics, "session_duration_histogram", histogram)

    metrics.record_session_completion(outcome="finalized")
    metrics.record_session_duration(42.5, outcome="finalized")

    assert counter.calls == [(1, {"outcome": "finalized"})]
    assert histogram.calls == [(42.5, {"outcome": "finalized"})]


def test_phase6_cache_hit_ratio_is_clamped_by_model():
    metrics._cache_hit_ratios.clear()

    metrics.record_cache_hit_ratio(
        model="gemini-test",
        input_tokens=100,
        cache_read_tokens=125,
    )

    assert metrics._cache_hit_ratios == {"gemini-test": 1.0}


def test_phase6_safety_metrics_have_required_attributes(monkeypatch):
    safety_counter = _FakeCounter()
    circuit_counter = _FakeCounter()
    monkeypatch.setattr(metrics, "safety_finish_reason_counter", safety_counter)
    monkeypatch.setattr(metrics, "cost_circuit_counter", circuit_counter)

    metrics.record_safety_finish_reason(model="gemini-test")
    metrics.record_cost_circuit_tripped(session_id_hash="abc123")

    assert safety_counter.calls == [(1, {"model": "gemini-test"})]
    assert circuit_counter.calls == [(1, {"session_id_hash": "abc123"})]
