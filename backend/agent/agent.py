"""
ADK agent definition — Expert IT Business Consultant.
"""

from google.adk.agents import Agent

from .prompt import SYSTEM_PROMPT

from dotenv import load_dotenv

load_dotenv()

# ADK model string for Gemini 3.1. Pro Pro on Vertex AI
MODEL = "gemini-3.1-pro-preview"

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
