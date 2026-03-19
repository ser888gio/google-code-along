"""
Generates a populated SRS Word document (.docx) from structured SRS data.

Takes the SRS JSON produced by compile_srs_json_from_session and writes
each section into a properly formatted Word document.
"""

import io
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def _set_heading_color(paragraph, color: tuple[int, int, int]):
    """Set the font color on all runs in a heading paragraph."""
    for run in paragraph.runs:
        run.font.color.rgb = RGBColor(*color)


def _add_section_heading(doc: Document, text: str, level: int):
    """Add a numbered heading at the given level (1-4)."""
    p = doc.add_heading(text, level=level)
    colors = {
        1: (26, 58, 42),   # dark green
        2: (42, 74, 58),
        3: (60, 100, 80),
        4: (80, 120, 100),
    }
    _set_heading_color(p, colors.get(level, (0, 0, 0)))
    return p


def _add_placeholder(doc: Document, text: str):
    """Add body text. If text is empty/None, add a TBD note."""
    content = (text or "").strip()
    if not content:
        p = doc.add_paragraph()
        run = p.add_run("TBD — information to be gathered.")
        run.italic = True
        run.font.color.rgb = RGBColor(150, 150, 150)
    else:
        doc.add_paragraph(content)


def srs_json_to_docx(srs: dict) -> bytes:
    """Convert a structured SRS dict to a .docx file and return the bytes.

    Expected structure mirrors the SRS JSON schema with sections keyed as:
      introduction, overall_description, system_features,
      external_interface_requirements, nonfunctional_requirements,
      other_requirements, appendices
    Each value is a dict with sub-section fields.
    """
    doc = Document()

    # ── Title ──────────────────────────────────────────────────────────────────
    title_para = doc.add_heading("Software Requirements Specification", 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title_para.runs:
        run.font.color.rgb = RGBColor(26, 58, 42)

    intro = srs.get("introduction", {})
    project_name = intro.get("purpose", {}).get("product_name") or "Untitled Project"
    subtitle = doc.add_paragraph(project_name)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in subtitle.runs:
        run.bold = True
        run.font.size = Pt(14)

    doc.add_paragraph()

    # ── 1. Introduction ────────────────────────────────────────────────────────
    _add_section_heading(doc, "1. Introduction", 1)

    _add_section_heading(doc, "1.1 Purpose", 2)
    _add_placeholder(doc, intro.get("purpose", {}).get("content"))

    _add_section_heading(doc, "1.2 Project Scope", 2)
    _add_placeholder(doc, intro.get("project_scope"))

    _add_section_heading(doc, "1.3 Requester", 2)
    _add_placeholder(doc, intro.get("requester"))

    _add_section_heading(doc, "1.4 Product Owner", 2)
    _add_placeholder(doc, intro.get("product_owner"))

    _add_section_heading(doc, "1.5 Sponsor", 2)
    _add_placeholder(doc, intro.get("sponsor"))

    _add_section_heading(doc, "1.6 Delivery Responsibility", 2)
    _add_placeholder(doc, intro.get("delivery_responsibility"))

    # ── 2. Overall Description ─────────────────────────────────────────────────
    _add_section_heading(doc, "2. Overall Description", 1)
    od = srs.get("overall_description", {})

    _add_section_heading(doc, "2.1 Product Perspective", 2)
    _add_placeholder(doc, od.get("product_perspective"))

    _add_section_heading(doc, "2.2 Product Features", 2)
    _add_placeholder(doc, od.get("product_features"))

    _add_section_heading(doc, "2.3 User Classes and Characteristics", 2)
    _add_placeholder(doc, od.get("user_classes"))

    _add_section_heading(doc, "2.4 Operating Environment", 2)
    _add_placeholder(doc, od.get("operating_environment"))

    _add_section_heading(doc, "2.5 Design and Implementation Constraints", 2)
    _add_placeholder(doc, od.get("design_constraints"))

    _add_section_heading(doc, "2.6 User Documentation", 2)
    _add_placeholder(doc, od.get("user_documentation"))

    _add_section_heading(doc, "2.7 Assumptions and Dependencies", 2)
    _add_placeholder(doc, od.get("assumptions_and_dependencies"))

    # ── 3. System Features ─────────────────────────────────────────────────────
    _add_section_heading(doc, "3. System Features", 1)
    features: list = srs.get("system_features", [])
    if not features:
        _add_placeholder(doc, None)
    else:
        for idx, feature in enumerate(features, start=1):
            feature_name = feature.get("name", f"Feature {idx}")
            _add_section_heading(doc, f"3.{idx} {feature_name}", 2)

            _add_section_heading(doc, f"3.{idx}.1 Description and Priority", 3)
            _add_placeholder(doc, feature.get("description_and_priority"))

            _add_section_heading(doc, f"3.{idx}.2 Stimulus/Response Sequences", 3)
            _add_placeholder(doc, feature.get("stimulus_response"))

            _add_section_heading(doc, f"3.{idx}.3 Functional Requirements", 3)
            reqs: dict = feature.get("functional_requirements", {})
            if reqs:
                for req_id, req_text in reqs.items():
                    p = doc.add_paragraph(style="List Bullet")
                    run = p.add_run(f"{req_id}: ")
                    run.bold = True
                    p.add_run(req_text or "TBD")
            else:
                _add_placeholder(doc, None)

    # ── 4. External Interface Requirements ────────────────────────────────────
    _add_section_heading(doc, "4. External Interface Requirements", 1)
    ei = srs.get("external_interface_requirements", {})

    _add_section_heading(doc, "4.1 User Interfaces", 2)
    _add_placeholder(doc, ei.get("user_interfaces"))

    _add_section_heading(doc, "4.2 Hardware Interfaces", 2)
    _add_placeholder(doc, ei.get("hardware_interfaces"))

    _add_section_heading(doc, "4.3 Software Interfaces", 2)
    _add_placeholder(doc, ei.get("software_interfaces"))

    _add_section_heading(doc, "4.4 Communications Interfaces", 2)
    _add_placeholder(doc, ei.get("communications_interfaces"))

    # ── 5. Other Nonfunctional Requirements ───────────────────────────────────
    _add_section_heading(doc, "5. Other Nonfunctional Requirements", 1)
    nf = srs.get("nonfunctional_requirements", {})

    _add_section_heading(doc, "5.1 Performance Requirements", 2)
    _add_placeholder(doc, nf.get("performance"))

    _add_section_heading(doc, "5.2 Safety Requirements", 2)
    _add_placeholder(doc, nf.get("safety"))

    _add_section_heading(doc, "5.3 Security Requirements", 2)
    _add_placeholder(doc, nf.get("security"))

    _add_section_heading(doc, "5.4 Software Quality Attributes", 2)
    _add_placeholder(doc, nf.get("quality_attributes"))

    # ── 6. Other Requirements ─────────────────────────────────────────────────
    _add_section_heading(doc, "6. Other Requirements", 1)
    _add_placeholder(doc, srs.get("other_requirements"))

    # ── Appendices ────────────────────────────────────────────────────────────
    _add_section_heading(doc, "Appendices", 1)
    app = srs.get("appendices", {})

    _add_section_heading(doc, "Appendix A: Glossary", 2)
    _add_placeholder(doc, app.get("glossary"))

    _add_section_heading(doc, "Appendix B: Analysis Models", 2)
    _add_placeholder(doc, app.get("analysis_models"))

    _add_section_heading(doc, "Appendix C: Issues List", 2)
    _add_placeholder(doc, app.get("issues_list"))

    # ── Serialize ─────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
