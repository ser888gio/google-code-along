"""
Firestore persistence for the SRS data collected during a session.

Each session is stored as a single Firestore document at:
  Collection : srs_sessions
  Document ID: <session_id>

The document structure mirrors the full SRS JSON schema so the frontend
can display every field in real-time.  `upsert_srs_fields` uses
`set(..., merge=True)` so repeated calls overwrite only the fields that
have a value — previously filled fields are never erased.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "srs_sessions")


def _client() -> firestore.Client:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    return firestore.Client(project=project)


def _srs_to_doc(session_id: str, srs: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested SRS JSON dict into a Firestore-compatible document."""
    sections = srs.get("sections", {})
    intro = sections.get("1. Introduction", {})
    overall = sections.get("2. Overall Description", {})
    features = sections.get("3. System Features", {})
    interfaces = sections.get("4. External Interface Requirements", {})
    nonfunc = sections.get("5. Other Nonfunctional Requirements", {})
    other = sections.get("6. Other Requirements", {})
    appendices = sections.get("Appendices", {})

    doc: dict[str, Any] = {
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    def _set(key: str, value: Any) -> None:
        """Only include the key if the value is non-empty."""
        if value is not None and str(value).strip():
            doc[key] = value

    # 1. Introduction
    _set("s1_1_purpose",                 intro.get("1.1 Purpose"))
    _set("s1_2_project_scope",           intro.get("1.2 Project Scope"))
    _set("s1_3_requester",               intro.get("1.3 Requester"))
    _set("s1_4_product_owner",           intro.get("1.4 Product Owner"))
    _set("s1_5_sponsor",                 intro.get("1.5 Sponsor"))
    _set("s1_6_delivery_responsibility", intro.get("1.6 Delivery Responsibility"))

    # 2. Overall Description
    _set("s2_1_product_perspective",      overall.get("2.1 Product Perspective"))
    _set("s2_2_product_features",         overall.get("2.2 Product Features"))
    _set("s2_3_user_classes",             overall.get("2.3 User Classes and Characteristics"))
    _set("s2_4_operating_environment",    overall.get("2.4 Operating Environment"))
    _set("s2_5_design_constraints",       overall.get("2.5 Design and Implementation Constraints"))
    _set("s2_6_user_documentation",       overall.get("2.6 User Documentation"))
    _set("s2_7_assumptions_dependencies", overall.get("2.7 Assumptions and Dependencies"))

    # 3. System Features — store as JSON string (nested structure)
    if features:
        _set("s3_system_features", json.dumps(features, ensure_ascii=False))

    # 4. External Interface Requirements
    _set("s4_1_user_interfaces",           interfaces.get("4.1 User Interfaces"))
    _set("s4_2_hardware_interfaces",       interfaces.get("4.2 Hardware Interfaces"))
    _set("s4_3_software_interfaces",       interfaces.get("4.3 Software Interfaces"))
    _set("s4_4_communications_interfaces", interfaces.get("4.4 Communications Interfaces"))

    # 5. Nonfunctional Requirements
    _set("s5_1_performance",        nonfunc.get("5.1 Performance Requirements"))
    _set("s5_2_safety",             nonfunc.get("5.2 Safety Requirements"))
    _set("s5_3_security",           nonfunc.get("5.3 Security Requirements"))
    _set("s5_4_quality_attributes", nonfunc.get("5.4 Software Quality Attributes"))

    # 6. Other Requirements
    _set("s6_other_requirements", other.get("description"))

    # Appendices
    _set("appendix_a_glossary",        appendices.get("Appendix A: Glossary"))
    _set("appendix_b_analysis_models", appendices.get("Appendix B: Analysis Models"))
    _set("appendix_c_issues_list",     appendices.get("Appendix C: Issues List"))

    return doc


def upsert_srs_fields(session_id: str, srs: dict[str, Any]) -> None:
    """Write or merge the SRS data for *session_id* into Firestore.

    Uses `set(..., merge=True)` so only non-empty fields are written and
    previously stored data is never erased by a partial update.
    """
    doc = _srs_to_doc(session_id, srs)
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    ref.set(doc, merge=True)


def get_srs_fields(session_id: str) -> dict[str, Any] | None:
    """Return the stored SRS document for *session_id*, or None if not found."""
    client = _client()
    ref = client.collection(_COLLECTION).document(session_id)
    snap = ref.get()
    if not snap.exists:
        return None
    return snap.to_dict()
