"""
Main Orchestrator Agent — AI Business Analyst.

This is the only agent the user interacts with directly.
It orchestrates three sub-agents (research, discovery, finalizer) as ADK tools,
keeping them invisible to the user.

Sub-agent modules are imported here but defined in their own files:
  - research_agent  → agent/research_agent.py     (TODO: create)
  - discovery_agent → agent/discovery_agent.py    (TODO: create)
  - finalizer_agent → agent/finalizer_agent.py    (TODO: create)
"""

from dotenv import load_dotenv
from google.adk.agents import Agent

# TODO: import AgentTool from google.adk.tools once sub-agents are created
# from google.adk.tools import AgentTool
# from .research_agent import research_agent
# from .discovery_agent import discovery_agent
# from .finalizer_agent import finalizer_agent
from .prompt import ORCHESTRATOR_SYSTEM_PROMPT

load_dotenv()

# Gemini Pro — orchestrator needs strong reasoning to decide when to invoke sub-agents
ORCHESTRATOR_MODEL = "gemini-2.5-pro-preview-05-06"

# TODO: once sub-agents are defined, replace tools=[] with AgentTool wrappers:
#
#   tools=[
#       AgentTool(agent=research_agent),    # search GCS KB + Vertex AI Search
#       AgentTool(agent=discovery_agent),   # extract & track all 22 form fields
#       AgentTool(agent=finalizer_agent),   # produce final classification analysis
#   ]
#
# ADK AgentTool makes each sub-agent callable as a function tool.
# The orchestrator decides when to call them; the user never sees sub-agent calls directly.

orchestrator = Agent(
    name="business_analyst_orchestrator",
    description=(
        "AI Business Analyst that guides users through a structured discovery session "
        "to collect all required fields for an IT use case analysis, then produces a "
        "detailed analysis with technology recommendation, team profile, and priority tier."
    ),
    model=ORCHESTRATOR_MODEL,
    instruction=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=[],  # TODO: replace with AgentTool list above
)

# Keep legacy alias so existing main.py import does not break during transition
# TODO: remove this alias once main.py is updated to import `orchestrator` directly
rs_agent = orchestrator
