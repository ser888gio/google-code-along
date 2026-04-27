"""Prompts for the BPMN diagram generation agent."""

COMPLETENESS_PROMPT = """\
You are evaluating how complete a business requirements conversation is for generating \
a BPMN process diagram.

Analyze the conversation below and score it on a scale of 0–100 based on how much of \
the following information has been captured:

1. Current process (As-Is) — what steps exist today                   [20 points]
2. Desired future process (To-Be) — what the new flow should look like [20 points]
3. Key actors / roles / swim-lane participants                          [20 points]
4. Functional requirements — at least 3 concrete actions/steps         [20 points]
5. Decision points or branching conditions                             [10 points]
6. Start and end events / triggers                                     [10 points]

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{{
  "score": <integer 0-100>,
  "missing": [<short string describing each missing area>]
}}

Conversation:
---
{conversation}
---
"""

BPMN_GENERATION_PROMPT = """\
You are an expert business analyst. Based on the requirements conversation below, \
generate a Mermaid.js flowchart that represents the To-Be business process as a BPMN-style diagram.

Rules:
- Use `flowchart TD` syntax.
- Model swimlane participants as `subgraph` blocks (one per actor/role).
- Use rounded rectangles `([...])` for start/end events.
- Use rectangles `[...]` for tasks/activities.
- Use diamonds `{{...}}` for decision gateways.
- Label every arrow with a short action or condition where relevant.
- Keep node IDs short (A, B, C... or descriptive like req1, approval1).
- Do NOT include any explanation, markdown fences, or text outside the Mermaid diagram.
- Output ONLY the raw Mermaid syntax starting with `flowchart TD`.

Conversation:
---
{conversation}
---
"""
