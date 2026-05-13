"""Prompts for the DataFlow diagram generation agent."""

DATAFLOW_COMPLETENESS_PROMPT = """\
You are evaluating how complete a business requirements conversation is for generating \
a Data Flow Diagram (DFD).

Analyze the conversation below and score it on a scale of 0–100 based on how much of \
the following information has been captured:

1. External entities / actors that send or receive data              [20 points]
2. Core processes / functions that transform data                    [20 points]
3. Data flows between entities, processes, and data stores           [20 points]
4. Data stores (databases, files, caches) used by the system        [20 points]
5. Input and output data names (what is passed along each flow)      [10 points]
6. System boundary — what is inside vs. outside the system          [10 points]

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

DATAFLOW_GENERATION_PROMPT = """\
You are an expert business analyst and systems architect. Based on the requirements \
conversation below, generate a Mermaid.js diagram that represents the system as a \
Data Flow Diagram (DFD).

Rules:
- Use `flowchart LR` syntax (left-to-right layout).
- Represent **external entities** (actors, systems outside the boundary) as
  rectangles `[...]` prefixed with `ext_`.
- Represent **processes** (functions, transformations inside the system) as
  rounded boxes `([...])`.
- Represent **data stores** (databases, files, caches) as cylinders `[(...)]`.
- Draw **data flows** as labelled directed arrows `-- <data name> -->` between nodes.
- Group internal nodes inside a `subgraph System Boundary` block.
- Keep node IDs short and descriptive (e.g., ext_user, proc_login, store_users).
- Do NOT include any explanation, markdown fences, or text outside the Mermaid diagram.
- Output ONLY the raw Mermaid syntax starting with `flowchart LR`.

Conversation:
---
{conversation}
---
"""
