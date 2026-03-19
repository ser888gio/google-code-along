"""Prompt for structured SRS context extraction from a conversation."""

RS_EXTRACTION_PROMPT = """\
You are analyzing a business requirements conversation between a user and an AI consultant.

Your task is to extract any information that has already been discussed and map it to the
8 fields of a Discovery Session agenda.

You must return ONLY valid JSON — no markdown fences, no commentary, no explanation.

Analyze the conversation below and return a JSON object with exactly this structure:

{
  "completeness": <integer 0-100 reflecting overall discovery completeness>,
  "sections": {
    "1_context":              { "filled": <bool>, "content": <string or null> },
    "1_business_problem":     { "filled": <bool>, "content": <string or null> },
    "2_target_state":         { "filled": <bool>, "content": <string or null> },
    "2_success":              { "filled": <bool>, "content": <string or null> },
    "3_scope_in_out":         { "filled": <bool>, "content": <string or null> },
    "3_boundaries":           { "filled": <bool>, "content": <string or null> },
    "4_data_systems":         { "filled": <bool>, "content": <string or null> },
    "4_integrations_access":  { "filled": <bool>, "content": <string or null> }
  }
}

What each key maps to:

Block 1 — Context & Business Problem:
- "1_context": How does it work today? High-level current process description and where \
it hurts. What triggered the request (audit, legislation, deadline, efficiency goal).
- "1_business_problem": Who is affected — users, teams, approximate number of people or \
business units. The core pain points and frustrations.

Block 2 — Target State & Success:
- "2_target_state": What exactly should be different? The desired future state compared \
to today.
- "2_success": 3–5 measurable or observable success criteria. Priority classification \
of goals as must-have / should-have / nice-to-have.

Block 3 — Scope & Boundaries:
- "3_scope_in_out": In-scope items: features, processes, reports, automations. \
Out-of-scope items: what we are consciously not doing now.
- "3_boundaries": Dependencies on other teams, ongoing projects, subject-matter-expert \
availability.

Block 4 — Data, Systems, Integrations & Access:
- "4_data_systems": What data is needed, where does it come from, and who owns it? \
Data sensitivity (personal data, financial sensitivity, contracts).
- "4_integrations_access": Integration needs — SAP, data marts, SharePoint, email, \
documents, and other systems that must connect.

Rules:
- Set "filled" to true ONLY when there is substantive, specific information in the \
conversation for that field — not just a vague mention or question from the consultant.
- "content" must be a concise prose summary (2-5 sentences) of what was confirmed for that \
field. Use null when "filled" is false.
- "completeness" reflects how much of the full discovery has been gathered. Weight all \
8 fields equally (each worth ~12.5%).
- Do NOT invent or infer information not explicitly stated or confirmed by the user.
- "content" must be null (not "") when "filled" is false.

Conversation:
---
{conversation}
---
"""
