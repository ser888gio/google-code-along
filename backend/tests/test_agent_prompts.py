from prompts.agent import FINALIZER_SYSTEM_PROMPT, ORCHESTRATOR_SYSTEM_PROMPT


def test_orchestrator_prompt_requires_reply_language_to_follow_latest_user_message():
    assert "same language as the user's latest message" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "If the user writes in Czech, respond in Czech." in ORCHESTRATOR_SYSTEM_PROMPT
    assert "If the user writes in English, respond in English." in ORCHESTRATOR_SYSTEM_PROMPT
    assert "Always collect use_case_title in English" in ORCHESTRATOR_SYSTEM_PROMPT


def test_finalizer_prompt_requires_report_language_to_follow_conversation_language():
    assert "Determine the report language from the user's language" in FINALIZER_SYSTEM_PROMPT
    assert "If the user speaks mostly Czech" in FINALIZER_SYSTEM_PROMPT
    assert "If the user speaks mostly English" in FINALIZER_SYSTEM_PROMPT
    assert "use_case_form.use_case_title in English" in FINALIZER_SYSTEM_PROMPT
