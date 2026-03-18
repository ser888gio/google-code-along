"""
ADK agent definition — Expert IT Business Consultant.
"""

from google.adk.agents import Agent

from .prompt import SYSTEM_PROMPT

# ADK model string for Gemini 1.5 Pro on Vertex AI
MODEL = "gemini-3-pro"

rs_agent = Agent(
    name="rs_consultant",
    description=(
        "An expert IT Business Consultant that guides users through "
        "a structured discovery process to create a Requirement "
        "Specification document."
    ),
    model=MODEL,
    instruction=SYSTEM_PROMPT,
    tools=[],
)
