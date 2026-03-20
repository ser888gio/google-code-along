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

import os
from functools import cached_property

from config import MODEL_AUDIO, MODEL_ORCHESTRATOR, AUDIO_REGION
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types as genai_types
from prompts.agent import ORCHESTRATOR_SYSTEM_PROMPT

from .research_agent import RESEARCH_TOOLS


# ---------------------------------------------------------------------------
# Region-pinned Gemini LLM for the Live API
# ---------------------------------------------------------------------------


class _RegionPinnedGemini(Gemini):
    """Gemini LLM subclass that pins the Live API client to a specific region.

    The default Gemini class reads GOOGLE_CLOUD_REGION from the environment,
    which may point to a multi-region (e.g. 'eur3') that doesn't support
    bidiGenerateContent. This subclass overrides _live_api_client to use
    a Vertex AI client pinned to AUDIO_REGION.
    """

    _audio_region: str = AUDIO_REGION

    @cached_property
    def _live_api_client(self):
        from google.genai import Client

        return Client(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=self._audio_region,
            http_options=genai_types.HttpOptions(
                headers=self._tracking_headers(),
                api_version=self._live_api_version,
            ),
        )


# ---------------------------------------------------------------------------
# Text orchestrator agent
# ---------------------------------------------------------------------------

# Research tools are wired directly on the orchestrator so it can call them inline
# during the conversation without the indirection of a sub-agent hop.
#
# Discovery tracking and finalization are handled outside the ADK runner:
#   - main.py calls extract_discovery_fields() after every turn (fire-and-forget)
#   - main.py detects [FINALIZING] marker and calls run_finalizer() as a background task
#
# TODO (future): wire AgentTool(agent=research_agent) when the research sub-agent
#       needs to do multi-step retrieval (read a specific GCS document after listing).
#       For the demo the three function tools below are sufficient.

orchestrator = Agent(
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

# Keep legacy alias so existing main.py import does not break during transition
# TODO: remove this alias once main.py is updated to import `orchestrator` directly
rs_agent = orchestrator


# ---------------------------------------------------------------------------
# Audio agent for bidi voice streaming
# ---------------------------------------------------------------------------

audio_agent = Agent(
    name="business_analyst_audio",
    description=(
        "AI Business Analyst (voice mode) that guides users through a structured "
        "discovery session via real-time voice conversation."
    ),
    model=_RegionPinnedGemini(model=MODEL_AUDIO),
    instruction=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=[],
)
