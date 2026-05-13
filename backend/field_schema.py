"""Canonical Requirements Specification field schema.

Keep field metadata, direct-input behavior, and lightweight matching heuristics
here so extraction, persistence, exports, and the frontend all derive from the
same source.
"""

from __future__ import annotations

from typing import Any, TypedDict


class FieldDef(TypedDict, total=False):
    label: str
    required: bool
    section: int
    direct_input: bool
    ai_extractable: bool
    multiline: bool
    direct_chat: bool
    match_terms: list[str]
    direct_chat_patterns: list[str]
    validation_mode: str
    expected_shape: str
    example_good: str
    rubric: list[str]


SECTION_TITLES: dict[int, str] = {
    1: "Identity & Current State",
    2: "Target State",
    3: "Value & ROI",
    4: "Priority & Risk",
    5: "Technical Context",
    6: "Additional",
}

FIELD_SCHEMA: dict[str, FieldDef] = {
    "use_case_title": {
        "label": "Use Case Title (EN)",
        "required": True,
        "section": 1,
        "direct_input": True,
        "ai_extractable": True,
        "direct_chat": True,
        "match_terms": ["use case title", "nazev", "title"],
        "direct_chat_patterns": [
            r"\buse\s+case\s+title\b",
            r"\bnazev\b.*\buse\s+case\b",
            r"\bnazev\b.*\bpripad\b",
        ],
        "validation_mode": "soft",
        "expected_shape": "Short English noun phrase naming the deliverable (2-6 words).",
        "example_good": "Patents reporting",
        "rubric": [
            "Names the deliverable, not the problem",
            "Written in English",
            "Concise (under ~6 words)",
        ],
    },
    "department": {
        "label": "Customer Department",
        "required": True,
        "section": 1,
        "direct_input": True,
        "ai_extractable": True,
        "direct_chat": True,
        "match_terms": ["department", "oddeleni", "utvar", "business unit"],
        "direct_chat_patterns": [
            r"\bdepartment\b",
            r"\boddeleni\b",
            r"\butvar\b",
            r"\bbusiness\s+unit\b",
        ],
        "validation_mode": "strict",
        "expected_shape": "Specific department / business unit name or code.",
        "example_good": "Patent department (3-letter code level)",
        "rubric": [
            "Identifies a specific department, not a generic role",
            "Includes code or hierarchy level if relevant",
        ],
    },
    "requestor": {
        "label": "Requestor",
        "required": True,
        "section": 1,
        "direct_input": True,
        "ai_extractable": True,
        "direct_chat": True,
        "match_terms": ["requestor", "zadatel", "zadavatel"],
        "direct_chat_patterns": [r"\brequestor\b", r"\bzadatel\b", r"\bzadavatel\b"],
        "validation_mode": "strict",
        "expected_shape": "Name, email, or department-code of the person making the request.",
        "example_good": "Jane Novak, Patent department",
        "rubric": [
            "Identifies a specific person or department code",
            "Not just a role title like 'manager'",
        ],
    },
    "product_owner": {
        "label": "Product Owner",
        "required": True,
        "section": 1,
        "direct_input": True,
        "ai_extractable": True,
        "direct_chat": True,
        "match_terms": [
            "product owner",
            "produktovy vlastnik",
            "vlastnik produktu",
            "owner",
        ],
        "direct_chat_patterns": [
            r"\bproduct\s+owner\b",
            r"\bproduktov(?:y|eho)\s+vlastnik\b",
            r"\bvlastnik\s+produktu\b",
        ],
        "validation_mode": "strict",
        "expected_shape": "Named individual designated as product owner.",
        "example_good": "John Smith (Patent dept. lead)",
        "rubric": [
            "Identifies a named person",
            "Not just a department or 'TBD'",
        ],
    },
    "target_users": {
        "label": "Target Users",
        "required": True,
        "section": 1,
        "validation_mode": "soft",
        "expected_shape": "Who will consume the deliverable (audience, roles, or departments).",
        "example_good": "Recipients of the annual presentation; all employees viewing the BI report.",
        "rubric": [
            "Identifies the audience by role, group, or department",
            "Distinguishes primary vs. secondary users when relevant",
        ],
    },
    "report_frequency": {
        "label": "Refresh Frequency",
        "required": False,
        "section": 1,
        "validation_mode": "strict",
        "expected_shape": "One of: Daily, Weekly, Monthly, Ad-hoc — plus any cadence detail.",
        "example_good": "Monthly refresh; annual report cycle in January.",
        "rubric": [
            "Picks an explicit cadence from the standard list",
            "Notes any special cycles (annual, on-demand)",
        ],
    },
    "process_as_is": {
        "label": "Process Description / As-Is",
        "required": True,
        "section": 1,
        "validation_mode": "soft",
        "expected_shape": "Description of how the work is done today, including manual steps and pain points.",
        "example_good": "Manual processing of data from WinPAT and supporting Excel files into a PowerPoint report; manual distribution by email; ad-hoc lookups in WinPAT to answer employee questions.",
        "rubric": [
            "Describes concrete current-state steps",
            "Mentions tools or systems used today",
            "Names at least one pain point",
        ],
    },
    "process_context": {
        "label": "Process Context",
        "required": True,
        "section": 1,
        "validation_mode": "soft",
        "expected_shape": "What happens before/after this process and how it connects to other processes.",
        "example_good": "Triggered annually after patent application data is closed for the year; output feeds into management presentation cycle.",
        "rubric": [
            "Describes upstream input or trigger",
            "Describes downstream consumer or follow-up",
        ],
    },
    "trigger": {
        "label": "Trigger",
        "required": True,
        "section": 1,
        "validation_mode": "soft",
        "expected_shape": "The event, deadline, or condition that starts this process.",
        "example_good": "Annual review cycle — required by 14.01.2026.",
        "rubric": [
            "Names a concrete trigger (date, event, request type)",
            "Indicates urgency or recurrence",
        ],
    },
    "purpose_to_be": {
        "label": "Purpose / To-Be",
        "required": True,
        "section": 2,
        "validation_mode": "soft",
        "expected_shape": "The desired future state — what changes, what improves, what new capability is enabled.",
        "example_good": "Automate annual report preparation, eliminate manual rewriting and errors, expand the report with historical insight, ensure BI report availability via a single link without forwarding presentations.",
        "rubric": [
            "Describes a concrete future-state outcome",
            "Names at least one improvement vs. as-is",
            "Mentions a measurable or visible change",
        ],
    },
    "key_business_questions": {
        "label": "Key Business Questions",
        "required": True,
        "section": 2,
        "multiline": True,
        "validation_mode": "soft",
        "expected_shape": "List of 2-5 specific business questions the deliverable must answer.",
        "example_good": "1) How many patent applications were filed in a given period? 2) How does the count break down by department over time? 3) Who in each department has the most applications?",
        "rubric": [
            "Lists at least 2 concrete questions",
            "Each question is answerable from data",
            "Questions reflect business decisions, not internals",
        ],
    },
    "kpis_and_metrics": {
        "label": "KPIs & Metrics",
        "required": True,
        "section": 2,
        "multiline": True,
        "validation_mode": "strict",
        "expected_shape": "Named metrics with definition, unit, and breakdown detail.",
        "example_good": "Number of patent applications: count of PRIO + EP + PCT in the selected period. Unit: count.",
        "rubric": [
            "Names each KPI explicitly",
            "States the unit (count, %, currency, hours)",
            "Defines how it is calculated",
        ],
    },
    "saved_time_hours_per_year": {
        "label": "Saved Time (hours/year)",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["saved time", "uspora casu", "hours"],
        "validation_mode": "strict",
        "expected_shape": "Numeric estimate of hours saved per year (approximate is OK).",
        "example_good": "~120 hours/year across the patent team",
        "rubric": [
            "Provides a numeric value, not just 'a lot'",
            "Time horizon is per year",
        ],
    },
    "cost_saving": {
        "label": "Cost Saving",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["cost saving", "naklady", "uspora nakladu"],
        "validation_mode": "strict",
        "expected_shape": "Estimated cost reduction in money terms (approximate is OK).",
        "example_good": "~€8,000 / year in analyst time",
        "rubric": [
            "Provides a money figure or explicit 'unknown'",
            "Notes the basis (labour, licences, etc.) if known",
        ],
    },
    "revenue_increase": {
        "label": "Revenue Increase",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["revenue", "vynos", "trzby"],
        "validation_mode": "strict",
        "expected_shape": "Estimated incremental revenue (approximate or explicit 'unknown' is OK).",
        "example_good": "N/A — internal reporting use case",
        "rubric": [
            "Provides a figure or explicit 'unknown'/'N/A'",
        ],
    },
    "impacted_users": {
        "label": "Impacted Users",
        "required": True,
        "section": 3,
        "validation_mode": "strict",
        "expected_shape": "Number of users affected and how much time each saves.",
        "example_good": "~15 patent department employees; ~8 hours/year each.",
        "rubric": [
            "Gives a user count (or range)",
            "Gives time-saved-per-user or aggregate savings",
        ],
    },
    "add_value": {
        "label": "Added Value",
        "required": True,
        "section": 3,
        "validation_mode": "soft",
        "expected_shape": "Qualitative or strategic value beyond pure cost savings.",
        "example_good": "Self-service access for employees; historical trend visibility; reduced risk of manual transcription errors.",
        "rubric": [
            "Names at least one qualitative benefit",
            "Goes beyond money/time savings",
        ],
    },
    "time_criticality": {
        "label": "Time Criticality",
        "required": True,
        "section": 4,
        "validation_mode": "strict",
        "expected_shape": "Priority level and any regulatory/business deadline.",
        "example_good": "Priority: Medium. Required by 14.01.2026 for annual review.",
        "rubric": [
            "Picks a priority level (Low / Medium / High)",
            "Names a deadline or explicitly says none",
        ],
    },
    "strategic_impact": {
        "label": "Strategic Impact",
        "required": True,
        "section": 4,
        "validation_mode": "soft",
        "expected_shape": "Strategic importance to the organisation and the way it matters.",
        "example_good": "Supports IP strategy reporting to the executive team; aligns with the company-wide BI self-service initiative.",
        "rubric": [
            "Connects to a named strategic objective or initiative",
            "Not just 'important' without justification",
        ],
    },
    "risk_avoidance": {
        "label": "Risk Avoidance",
        "required": False,
        "section": 4,
        "validation_mode": "soft",
        "expected_shape": "Specific financial or operational risk addressed, plus estimated amount if known.",
        "example_good": "Mitigates risk of inaccurate annual figures distributed to executives; ~€20k operational exposure.",
        "rubric": [
            "Names a specific risk avoided",
            "Provides an estimated amount or explicit 'unknown'",
        ],
    },
    "acceptance_criteria": {
        "label": "Acceptance Criteria",
        "required": True,
        "section": 4,
        "multiline": True,
        "validation_mode": "soft",
        "expected_shape": "List of conditions that must hold for the deliverable to be accepted.",
        "example_good": "Counts in Power BI match WinPAT for selected period; correct department mapping; replaces page 2 of the PPT with interactive filtering; export/share without emailing the PPT; employees can filter their own applications.",
        "rubric": [
            "Lists at least 3 acceptance conditions",
            "Each condition is verifiable",
            "Covers data correctness and user-visible behaviour",
        ],
    },
    "systems_and_tools": {
        "label": "Systems & Tools Involved",
        "required": True,
        "section": 5,
        "validation_mode": "strict",
        "expected_shape": "Named systems and tools in the current process or target solution.",
        "example_good": "WinPAT (source application), Excel exports, Databricks (planned integration), Power BI (target).",
        "rubric": [
            "Names at least one source system",
            "Names target/output platform when known",
        ],
    },
    "document_types": {
        "label": "Types of Documents Involved",
        "required": True,
        "section": 5,
        "validation_mode": "strict",
        "expected_shape": "Specific document types (PDF, Excel, contract, invoice, etc.).",
        "example_good": "Excel exports from WinPAT; PowerPoint annual report; tabular patent application data.",
        "rubric": [
            "Names at least one document type or data format",
            "Distinguishes input vs. output where relevant",
        ],
    },
    "dimensions_and_cuts": {
        "label": "Dimensions & Data Cuts",
        "required": False,
        "section": 5,
        "multiline": True,
        "validation_mode": "strict",
        "expected_shape": "Slice/dice dimensions (time, organisation, scenario, etc.) and critical combinations.",
        "example_good": "Time: year (drill-down to quarter/month if available). Organisation: department hierarchy to 3-letter level. Critical combo: department × time.",
        "rubric": [
            "Names time dimension and granularity",
            "Names organisational or other key dimensions",
            "Calls out critical combinations or N/A items",
        ],
    },
    "data_security_classification": {
        "label": "Data Security Classification",
        "required": True,
        "section": 5,
        "validation_mode": "strict",
        "expected_shape": "Classification level (Public / Internal / Confidential / Restricted) plus any RLS rules.",
        "example_good": "Confidential at source (patent names); Internal in the report after redaction; visible to all employees.",
        "rubric": [
            "Picks an explicit classification level",
            "Notes who may access (RLS / audience)",
        ],
    },
    "solution_type": {
        "label": "Solution Type",
        "required": True,
        "section": 5,
        "validation_mode": "strict",
        "expected_shape": "Probable solution category (Power BI, Power Platform, custom app, SharePoint, SAP extension, etc.).",
        "example_good": "Power BI report (analytical) backed by Databricks once available, Excel exports in the interim.",
        "rubric": [
            "Picks one solution category",
            "Mentions backing data layer if known",
        ],
    },
    "comments": {
        "label": "Comments",
        "required": False,
        "section": 6,
        "direct_input": True,
        "ai_extractable": False,
        "multiline": True,
        "match_terms": ["comment", "poznamka"],
        "validation_mode": "soft",
        "expected_shape": "Any additional useful information not covered elsewhere.",
        "example_good": "Patent titles must be excluded for confidentiality during the first months.",
        "rubric": [
            "Free-form, optional",
        ],
    },
    "attachments": {
        "label": "Attachments (GCS paths)",
        "required": False,
        "section": 6,
        "direct_input": True,
        "ai_extractable": False,
        "multiline": True,
        "match_terms": ["attachment", "priloha"],
        "validation_mode": "soft",
        "expected_shape": "List of attached files (GCS paths or filenames).",
        "example_good": "gs://uploads/patents_template.xlsx",
        "rubric": [
            "Lists filenames or paths if any",
        ],
    },
}

EMPTY_FIELDS: dict[str, dict[str, Any]] = {
    key: {"filled": False, "value": None} for key in FIELD_SCHEMA
}
REQUIRED_FIELDS = [key for key, field in FIELD_SCHEMA.items() if field["required"]]
OPTIONAL_FIELDS = [key for key, field in FIELD_SCHEMA.items() if not field["required"]]
FIELD_LABELS = {key: field["label"] for key, field in FIELD_SCHEMA.items()}
DIRECT_FIELD_KEYS = [
    key for key, field in FIELD_SCHEMA.items() if field.get("direct_input")
]
STRICT_DIRECT_FIELD_KEYS = [
    key
    for key, field in FIELD_SCHEMA.items()
    if field.get("direct_input") and not field.get("ai_extractable", True)
]
SUGGESTABLE_DIRECT_FIELD_KEYS = [
    key
    for key, field in FIELD_SCHEMA.items()
    if field.get("direct_input") and field.get("ai_extractable", True)
]
DIRECT_CHAT_FIELD_KEYS = [
    key for key, field in FIELD_SCHEMA.items() if field.get("direct_chat")
]
DIRECT_FIELD_LABELS = {key: FIELD_LABELS[key] for key in DIRECT_FIELD_KEYS}
DIRECT_FIELD_TERMS = {
    key: field["match_terms"]
    for key, field in FIELD_SCHEMA.items()
    if field.get("match_terms")
}

DEFERRED_ANSWER_PATTERNS = [
    r"\bnevim\b",
    r"\bnetusim\b",
    r"\bneznam\b",
    r"\bzjistim\b.*\bpozdeji\b",
    r"\bdoplnim(?:e)?\b.*\bpozdeji\b",
    r"\bpozdeji\b",
    r"\bpreskocit\b",
    r"\bted\b.*\bnevim\b",
    r"\bzatim\b.*\bne\b",
    r"\bzatim\b.*\bneni\b.*\bjasne\b",
    r"\bto\b.*\bzatim\b.*\bjedno\b",
    r"\bnemam\b",
    r"\bnemame\b.*\burceno\b",
    r"\bunknown\b",
    r"\bdon'?t\s+know\b",
    r"\bnot\s+sure\b",
    r"\blater\b",
    r"\btbd\b",
    r"\bn/a\b",
]


def build_sections() -> list[dict[str, Any]]:
    """Return ordered section metadata with nested field definitions."""
    sections: list[dict[str, Any]] = []
    for section_number, title in SECTION_TITLES.items():
        fields = []
        for key, field in FIELD_SCHEMA.items():
            if field["section"] != section_number:
                continue
            fields.append(
                {
                    "key": key,
                    "label": field["label"],
                    "required": field["required"],
                    "directInput": bool(field.get("direct_input")),
                    "multiline": bool(field.get("multiline")),
                    "validationMode": field.get("validation_mode", "soft"),
                    "expectedShape": field.get("expected_shape", ""),
                    "exampleGood": field.get("example_good", ""),
                    "rubric": list(field.get("rubric", [])),
                }
            )
        sections.append({"number": section_number, "title": title, "fields": fields})
    return sections


def format_field_rubric_block(field_key: str) -> str:
    """Return a compact markdown block describing what 'good' looks like for one field.

    Used inside extraction/classifier prompts so the LLM can judge answer quality
    against per-field expectations rather than a generic rule.
    """
    field = FIELD_SCHEMA.get(field_key)
    if not field:
        return ""
    parts: list[str] = []
    label = field.get("label")
    if label:
        parts.append(f"Field: {label} (key: {field_key})")
    mode = field.get("validation_mode")
    if mode:
        parts.append(f"Validation mode: {mode}")
    shape = field.get("expected_shape")
    if shape:
        parts.append(f"Expected shape: {shape}")
    rubric = field.get("rubric") or []
    if rubric:
        bullets = "\n".join(f"  - {item}" for item in rubric)
        parts.append(f"Must cover:\n{bullets}")
    example = field.get("example_good")
    if example:
        parts.append(f"Example of a strong answer: {example}")
    return "\n".join(parts)


def format_all_field_shapes() -> str:
    """One-line `expected_shape` summary per field, for the bulk extractor prompt."""
    lines: list[str] = []
    for key, field in FIELD_SCHEMA.items():
        shape = field.get("expected_shape")
        if not shape:
            continue
        mode = field.get("validation_mode", "soft")
        lines.append(f"- {key} [{mode}]: {shape}")
    return "\n".join(lines)


RS_TEMPLATE_SECTIONS = [
    (
        section["number"],
        section["title"],
        [(field["key"], field["label"]) for field in section["fields"]],
    )
    for section in build_sections()
]
