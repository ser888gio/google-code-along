from prompts.bpmn import BPMN_GENERATION_PROMPT, COMPLETENESS_PROMPT
from prompts.dataflow import DATAFLOW_COMPLETENESS_PROMPT, DATAFLOW_GENERATION_PROMPT


def test_bpmn_prompts_format_with_literal_json_and_mermaid_braces():
    conversation = "User: We approve invoices manually.\nConsultant: Who approves them?"

    completeness_prompt = COMPLETENESS_PROMPT.replace("{conversation}", conversation)
    generation_prompt = BPMN_GENERATION_PROMPT.replace("{conversation}", conversation)

    assert '"score": <integer 0-100>' in completeness_prompt
    assert '"missing": [<short string describing each missing area>]' in completeness_prompt
    assert "{...}" in generation_prompt
    assert conversation in completeness_prompt
    assert conversation in generation_prompt


def test_dataflow_prompts_format_with_literal_json():
    conversation = "User: Data moves from Salesforce into a report database."

    completeness_prompt = DATAFLOW_COMPLETENESS_PROMPT.replace("{conversation}", conversation)
    generation_prompt = DATAFLOW_GENERATION_PROMPT.replace("{conversation}", conversation)

    assert '"score": <integer 0-100>' in completeness_prompt
    assert '"missing": [<short string describing each missing area>]' in completeness_prompt
    assert conversation in completeness_prompt
    assert conversation in generation_prompt
