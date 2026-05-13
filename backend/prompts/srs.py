"""
Prompt for the SRS (Discovery Session) document compilation pipeline.

SRS_EXTRACTION_PROMPT - maps a full conversation transcript into the 4-block
                        Discovery Session structure used by the Word export.
"""

SRS_EXTRACTION_PROMPT = """\
You are an expert technical writer. Given the following conversation between
a user and an Discovery Agent, extract all discussed information and compile
it into a structured Discovery Session output document.

You MUST return ONLY valid JSON - no markdown fences, no commentary, no explanation.

Return a JSON object with exactly this structure:

{
  "context_and_business_problem": {
    "context": "<How it works today - high-level current process and where "
               "it hurts. What triggered the request (audit, legislation, "
               "deadline, efficiency goal).>",
    "business_problem": "<Who is affected - users, teams, approximate "
                        "number of people or business units. Core pain "
                        "points and frustrations.>"
  },
  "target_state_and_success": {
    "target_state": "<What exactly should be different? The desired future "
                    "state compared to today.>",
    "success": "<3-5 measurable or observable success criteria. Priority "
               "classification: must-have / should-have / nice-to-have.>"
  },
  "scope_and_boundaries": {
    "scope_in_out": "<In-scope: features, processes, reports, automations. "
                    "Out-of-scope: what we are consciously not doing now.>",
    "boundaries": "<Dependencies on other teams, ongoing projects, "
                  "SME availability.>"
  },
  "data_systems_integrations_access": {
    "data_systems": "<What data is needed, where does it come from, who "
                    "owns it? Data sensitivity (personal data, financial "
                    "sensitivity, contracts).>",
    "integrations_access": "<Integration needs - SAP, data marts, "
                           "SharePoint, email, documents, and other "
                           "systems that must connect.>"
  }
}

Rules:
- Use only information explicitly stated or confirmed by the user in the
  conversation.
- Use "TBD" for fields where no information was provided.
- Keep all text concise and professional - this is a formal specification
  document.

Conversation:
---
{conversation}
---
"""
