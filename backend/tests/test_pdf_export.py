"""
Task 6.3 — Tests for the PDF export module (generation/pdf_export.py).

Verifies that:
  - markdown_to_pdf returns non-empty bytes
  - The output is a valid PDF (starts with %PDF header)
  - Expected section headings appear in the raw PDF bytes
  - Edge cases (empty input, only headings, special characters) are handled
"""

from generation.pdf_export import markdown_to_pdf, _inline_markdown, _parse_markdown_to_flowables, _build_styles


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

SAMPLE_RS = """# Requirement Specification — Sales Report System

## 1. Executive Summary
Automate the manual daily sales reporting process.

## 2. Current State (As-Is)
A sales analyst spends **2 hours** every morning collecting data manually.

## 3. Desired State (To-Be)
An automated pipeline that delivers a PDF report by *07:00 CET* each business day.

## 4. Functional Requirements
FR-001: Connect to Salesforce via REST API
FR-002: Aggregate data by region and product line
FR-003: Generate a PDF report from a predefined template

## 5. Non-Functional Requirements
NFR-001: Report generation must complete within 3 minutes
NFR-002: System availability ≥ 99% on business days

## 6. Scope
### In Scope
- Salesforce CRM integration
- Automated email delivery

### Out of Scope
- Mobile application
- Real-time dashboards

## 7. Open Questions
- Who approves the PDF template design?
- Is the Salesforce sandbox available for testing?
"""


# ---------------------------------------------------------------------------
# markdown_to_pdf — output format
# ---------------------------------------------------------------------------


def test_pdf_returns_bytes():
    result = markdown_to_pdf(SAMPLE_RS)
    assert isinstance(result, bytes)


def test_pdf_is_non_empty():
    result = markdown_to_pdf(SAMPLE_RS)
    assert len(result) > 0


def test_pdf_starts_with_pdf_header():
    """Valid PDFs always start with the %PDF- magic bytes."""
    result = markdown_to_pdf(SAMPLE_RS)
    assert result[:5] == b"%PDF-"


def test_pdf_contains_expected_section_headings():
    """Key section names should appear as text in the raw PDF bytes."""
    result = markdown_to_pdf(SAMPLE_RS)
    for heading in [
        b"Executive Summary",
        b"Functional Requirements",
        b"Non-Functional Requirements",
        b"Open Questions",
    ]:
        assert heading in result, f"'{heading}' not found in PDF bytes"


def test_pdf_contains_requirement_ids():
    """Requirement IDs (FR-001, NFR-001) should appear in the PDF."""
    result = markdown_to_pdf(SAMPLE_RS)
    assert b"FR-001" in result
    assert b"NFR-001" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_input_produces_valid_pdf():
    """Empty markdown should still produce a valid (non-empty) PDF."""
    result = markdown_to_pdf("")
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"


def test_only_headings_produces_valid_pdf():
    markdown = "# Title\n## Section 1\n### Subsection 1.1\n#### Detail"
    result = markdown_to_pdf(markdown)
    assert result[:5] == b"%PDF-"
    assert len(result) > 100


def test_bullet_list_in_pdf():
    markdown = "## Items\n- First item\n- Second item\n* Third item\n"
    result = markdown_to_pdf(markdown)
    assert result[:5] == b"%PDF-"


def test_long_document_produces_pdf():
    """A long RS document with many sections should produce a multi-page PDF."""
    lines = ["# Big Specification\n"]
    for i in range(1, 21):
        lines.append(f"## Section {i}\n")
        lines.append(f"FR-{i:03d}: Requirement {i} description goes here.\n")
        lines.append(f"NFR-{i:03d}: Non-functional requirement {i}.\n")
        lines.append("- Bullet point one\n- Bullet point two\n\n")
    result = markdown_to_pdf("".join(lines))
    assert result[:5] == b"%PDF-"
    assert len(result) > 1000


# ---------------------------------------------------------------------------
# _inline_markdown — unit tests for inline parser
# ---------------------------------------------------------------------------


def test_inline_bold_double_asterisk():
    assert _inline_markdown("**bold text**") == "<b>bold text</b>"


def test_inline_bold_double_underscore():
    assert _inline_markdown("__bold text__") == "<b>bold text</b>"


def test_inline_italic_single_asterisk():
    assert _inline_markdown("*italic*") == "<i>italic</i>"


def test_inline_italic_single_underscore():
    assert _inline_markdown(" _italic_ ") == " <i>italic</i> "


def test_inline_mixed_bold_italic():
    result = _inline_markdown("This is **bold** and *italic* text.")
    assert "<b>bold</b>" in result
    assert "<i>italic</i>" in result


def test_inline_plain_text_unchanged():
    text = "No markdown here — just plain text."
    assert _inline_markdown(text) == text


# ---------------------------------------------------------------------------
# _parse_markdown_to_flowables — structure tests
# ---------------------------------------------------------------------------


def test_flowables_empty_markdown():
    styles = _build_styles()
    flowables = _parse_markdown_to_flowables("", styles)
    assert flowables == []


def test_flowables_h1_heading():
    styles = _build_styles()
    flowables = _parse_markdown_to_flowables("# Title", styles)
    assert len(flowables) == 1


def test_flowables_multiple_headings():
    styles = _build_styles()
    md = "# H1\n## H2\n### H3\n#### H4"
    flowables = _parse_markdown_to_flowables(md, styles)
    assert len(flowables) == 4


def test_flowables_bullet_list():
    styles = _build_styles()
    md = "- item one\n- item two\n* item three"
    flowables = _parse_markdown_to_flowables(md, styles)
    assert len(flowables) == 3


def test_flowables_requirement_ids():
    styles = _build_styles()
    md = "FR-001: First requirement\nNFR-002: Second requirement"
    flowables = _parse_markdown_to_flowables(md, styles)
    assert len(flowables) == 2


def test_flowables_paragraph_accumulation():
    """Consecutive non-empty lines without headings/bullets form one paragraph."""
    styles = _build_styles()
    md = "Line one\nLine two\nLine three"
    flowables = _parse_markdown_to_flowables(md, styles)
    assert len(flowables) == 1


def test_flowables_full_sample_document():
    styles = _build_styles()
    flowables = _parse_markdown_to_flowables(SAMPLE_RS, styles)
    # A full RS document should produce many flowables
    assert len(flowables) > 10
