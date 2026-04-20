"""
Main Orchestrator Agent — AI Business Analyst.

This is the only agent the user interacts with directly.

Architecture:
  - Orchestrator (this file): Gemini 2.5 Pro; has research FunctionTools wired in.
  - Research tools (research_agent.py): search_past_analyses, list_knowledge_base_docs,
    search_vertex_ai — called inline by the orchestrator during conversation.
  - Discovery extraction (discovery_agent.py): extract_discovery_fields() called by
    main.py as a fire-and-forget after every chat turn.
  - Finalizer (finalizer_agent.py): run_finalizer() called by main.py as an
    asyncio.create_task() when the orchestrator outputs [FINALIZING].

Two variants:
  - orchestrator / rs_agent: text-only, for structured discovery conversations
  - audio_agent:             native-audio model for bidirectional voice streaming (bidi)
"""

from functools import cached_property

from config import GOOGLE_API_KEY, MODEL_AUDIO, MODEL_ORCHESTRATOR
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types as genai_types
from prompts.agent import ORCHESTRATOR_SYSTEM_PROMPT

from .research_agent import RESEARCH_TOOLS


# ---------------------------------------------------------------------------
# API-key-pinned Gemini LLM for the Live API
# ---------------------------------------------------------------------------


class _ApiKeyGemini(Gemini):
    """Gemini LLM subclass that uses an API key for the Live API client."""

    @cached_property
    def _live_api_client(self):
        from google.genai import Client

        return Client(
            api_key=GOOGLE_API_KEY,
            http_options=genai_types.HttpOptions(
                headers=self._tracking_headers(),
                api_version=self._live_api_version,
            ),
        )


# ---------------------------------------------------------------------------
# Text orchestrator agent
# ---------------------------------------------------------------------------

rs_agent = Agent(
    name="business_analyst_orchestrator",
    description=(
        "AI Business Analyst that guides users through a structured discovery session "
        "to collect all required fields for an IT use case analysis, then produces a "
        "detailed analysis with technology recommendation, team profile, and priority tier."
    ),
    model=MODEL_ORCHESTRATOR,
    instruction=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=RESEARCH_TOOLS,  # search_past_analyses, list_knowledge_base_docs, search_vertex_ai
)


# ---------------------------------------------------------------------------
# Audio agent for bidi voice streaming
# ---------------------------------------------------------------------------

audio_agent = Agent(
    name="business_analyst_audio",
    description=(
        "AI Business Analyst (voice mode) that guides users through a structured "
        "discovery session via real-time voice conversation."
    ),
    model=_ApiKeyGemini(model=MODEL_AUDIO),
    instruction=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=[],
)
