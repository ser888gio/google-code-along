from types import SimpleNamespace

from agent.finalizer_agent import _extract_json_payload, _parse_finalizer_response


def test_extract_json_payload_accepts_plain_json():
    assert _extract_json_payload('{"ok": true}') == '{"ok": true}'


def test_extract_json_payload_strips_markdown_json_fence():
    raw = """```json
{"ok": true}
```"""

    assert _extract_json_payload(raw) == '{"ok": true}'


def test_parse_finalizer_response_reads_response_text_json():
    response = SimpleNamespace(text='```json\n{"answer": 42}\n```')

    assert _parse_finalizer_response(response) == {"answer": 42}
