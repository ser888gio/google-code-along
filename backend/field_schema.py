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
    },
    "process_as_is": {
        "label": "Process Description / As-Is",
        "required": True,
        "section": 1,
    },
    "process_context": {
        "label": "Process Context",
        "required": True,
        "section": 1,
    },
    "trigger": {"label": "Trigger", "required": True, "section": 1},
    "purpose_to_be": {"label": "Purpose / To-Be", "required": True, "section": 2},
    "saved_time_hours_per_year": {
        "label": "Saved Time (hours/year)",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["saved time", "uspora casu", "hours"],
    },
    "cost_saving": {
        "label": "Cost Saving",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["cost saving", "naklady", "uspora nakladu"],
    },
    "revenue_increase": {
        "label": "Revenue Increase",
        "required": False,
        "section": 3,
        "direct_input": True,
        "ai_extractable": False,
        "match_terms": ["revenue", "vynos", "trzby"],
    },
    "impacted_users": {"label": "Impacted Users", "required": True, "section": 3},
    "add_value": {"label": "Added Value", "required": True, "section": 3},
    "time_criticality": {
        "label": "Time Criticality",
        "required": True,
        "section": 4,
    },
    "strategic_impact": {
        "label": "Strategic Impact",
        "required": True,
        "section": 4,
    },
    "risk_avoidance": {
        "label": "Risk Avoidance",
        "required": False,
        "section": 4,
    },
    "systems_and_tools": {
        "label": "Systems & Tools Involved",
        "required": True,
        "section": 5,
    },
    "document_types": {
        "label": "Types of Documents Involved",
        "required": True,
        "section": 5,
    },
    "data_security_classification": {
        "label": "Data Security Classification",
        "required": True,
        "section": 5,
    },
    "solution_type": {"label": "Solution Type", "required": True, "section": 5},
    "comments": {
        "label": "Comments",
        "required": False,
        "section": 6,
        "direct_input": True,
        "ai_extractable": False,
        "multiline": True,
        "match_terms": ["comment", "poznamka"],
    },
    "attachments": {
        "label": "Attachments (GCS paths)",
        "required": False,
        "section": 6,
        "direct_input": True,
        "ai_extractable": False,
        "multiline": True,
        "match_terms": ["attachment", "priloha"],
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
                }
            )
        sections.append({"number": section_number, "title": title, "fields": fields})
    return sections


RS_TEMPLATE_SECTIONS = [
    (
        section["number"],
        section["title"],
        [(field["key"], field["label"]) for field in section["fields"]],
    )
    for section in build_sections()
]
