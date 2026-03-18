"""Prompt for structured RS context extraction from a conversation."""

RS_EXTRACTION_PROMPT = """\
You are analyzing a business requirements conversation between a user and an AI consultant.

Your task is to extract any information that has already been discussed and map it to the
sections of a Requirement Specification document.

You must return ONLY valid JSON — no markdown fences, no commentary, no explanation.

Analyze the conversation below and return a JSON object with exactly this structure:

{
  "completeness": <integer 0-100 reflecting overall RS completeness>,
  "sections": {
    "executive_summary":           { "filled": <boolean>, "content": <string or null> },
    "current_state":               { "filled": <boolean>, "content": <string or null> },
    "desired_future_state":        { "filled": <boolean>, "content": <string or null> },
    "scope":                       { "filled": <boolean>, "content": <string or null> },
    "functional_requirements":     { "filled": <boolean>, "content": <string or null> },
    "non_functional_requirements": { "filled": <boolean>, "content": <string or null> },
    "assumptions_and_constraints": { "filled": <boolean>, "content": <string or null> },
    "open_questions":              { "filled": <boolean>, "content": <string or null> }
  }
}

Rules:
- Set "filled" to true ONLY when there is substantive, specific information in the \
conversation for that section — not just a vague mention or question from the consultant.
- Set "content" to a concise prose summary (3-6 sentences max) of what was discussed for \
that section. Use null if the section has not been addressed at all.
- "executive_summary" should only be filled when you have enough context across multiple \
sections to write a meaningful project summary.
- "completeness" reflects how much of the full RS information has been gathered across all \
8 sections. Weight "functional_requirements" and "current_state" more heavily — they are the \
core of the document.
- Do NOT invent or infer information that was not explicitly stated or confirmed by the user.
- "content" must be null (not an empty string "") when "filled" is false.

Conversation:
---
{conversation}
---
"""
