"""Prompt for structured SRS context extraction from a conversation."""

RS_EXTRACTION_PROMPT = """\
You are analyzing a business requirements conversation between a user and an AI consultant.

Your task is to extract any information that has already been discussed and map it to the
subsections of a Software Requirements Specification (SRS) document following the IEEE 830 standard.

You must return ONLY valid JSON — no markdown fences, no commentary, no explanation.

Analyze the conversation below and return a JSON object with exactly this structure:

{
  "completeness": <integer 0-100 reflecting overall SRS completeness>,
  "sections": {
    "1_1_purpose":                   { "filled": <bool>, "content": <string or null> },
    "1_2_project_scope":             { "filled": <bool>, "content": <string or null> },
    "1_3_requester":                 { "filled": <bool>, "content": <string or null> },
    "1_4_product_owner":             { "filled": <bool>, "content": <string or null> },
    "1_5_sponsor":                   { "filled": <bool>, "content": <string or null> },
    "1_6_delivery_responsibility":   { "filled": <bool>, "content": <string or null> },
    "2_1_product_perspective":       { "filled": <bool>, "content": <string or null> },
    "2_2_product_features":          { "filled": <bool>, "content": <string or null> },
    "2_3_user_classes":              { "filled": <bool>, "content": <string or null> },
    "2_4_operating_environment":     { "filled": <bool>, "content": <string or null> },
    "2_5_design_constraints":        { "filled": <bool>, "content": <string or null> },
    "2_6_user_documentation":        { "filled": <bool>, "content": <string or null> },
    "2_7_assumptions_dependencies":  { "filled": <bool>, "content": <string or null> },
    "3_system_features":             { "filled": <bool>, "content": <string or null> },
    "4_1_user_interfaces":           { "filled": <bool>, "content": <string or null> },
    "4_2_hardware_interfaces":       { "filled": <bool>, "content": <string or null> },
    "4_3_software_interfaces":       { "filled": <bool>, "content": <string or null> },
    "4_4_communications_interfaces": { "filled": <bool>, "content": <string or null> },
    "5_1_performance":               { "filled": <bool>, "content": <string or null> },
    "5_2_safety":                    { "filled": <bool>, "content": <string or null> },
    "5_3_security":                  { "filled": <bool>, "content": <string or null> },
    "5_4_quality_attributes":        { "filled": <bool>, "content": <string or null> },
    "6_other_requirements":          { "filled": <bool>, "content": <string or null> },
    "appendix_a_glossary":           { "filled": <bool>, "content": <string or null> },
    "appendix_b_models":             { "filled": <bool>, "content": <string or null> },
    "appendix_c_issues":             { "filled": <bool>, "content": <string or null> }
  }
}

What each key maps to:
- "1_1_purpose": The product name and the purpose/scope of this SRS document.
- "1_2_project_scope": Short description of the software, its benefits, objectives, and goals.
- "1_3_requester": The name of the person who came up with the idea.
- "1_4_product_owner": The name of the person who will own and be responsible for the project.
- "1_5_sponsor": The name of the person financing the project.
- "1_6_delivery_responsibility": The name of the IT person responsible for delivering the product.
- "2_1_product_perspective": Context and origin of the product (new, replacement, or enhancement).
- "2_2_product_features": High-level summary of the main features.
- "2_3_user_classes": Types of users and their characteristics.
- "2_4_operating_environment": Hardware, OS, and software the system must work with.
- "2_5_design_constraints": Regulatory, policy, technology, or hardware constraints.
- "2_6_user_documentation": User manuals, online help, or tutorials to be delivered.
- "2_7_assumptions_dependencies": Assumed factors and project dependencies.
- "3_system_features": All system features with their priorities, stimulus/response, and REQ-N requirements.
- "4_1_user_interfaces": UI characteristics, GUI standards, screen layout, accessibility.
- "4_2_hardware_interfaces": Hardware components and their interfaces.
- "4_3_software_interfaces": Other software, APIs, databases, or libraries to integrate with.
- "4_4_communications_interfaces": Network protocols, communications requirements.
- "5_1_performance": Performance requirements under various conditions.
- "5_2_safety": Safety requirements, safeguards, certifications.
- "5_3_security": Security and privacy requirements, authentication.
- "5_4_quality_attributes": Availability, reliability, maintainability, usability, etc.
- "6_other_requirements": Database, legal, internationalization, or other uncategorized requirements.
- "appendix_a_glossary": Terms, acronyms, and abbreviations.
- "appendix_b_models": Data flow diagrams, class diagrams, or other analysis models.
- "appendix_c_issues": Open requirements issues, TBDs, pending decisions.

Rules:
- Set "filled" to true ONLY when there is substantive, specific information in the \
conversation for that subsection — not just a vague mention or question from the consultant.
- "content" must be a concise prose summary (2-5 sentences) of what was confirmed for that \
subsection. Use null when "filled" is false.
- Stakeholder subsections (1_3 through 1_6) are filled only when an actual name was provided.
- "3_system_features" summarizes ALL features discussed; include feature names, priorities, \
and key requirements inline.
- "completeness" reflects how much of the full SRS has been gathered. Weight \
"3_system_features" and "2_2_product_features" most heavily.
- Do NOT invent or infer information not explicitly stated or confirmed by the user.
- "content" must be null (not "") when "filled" is false.

Conversation:
---
{conversation}
---
"""
