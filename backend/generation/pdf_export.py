"""
Converts RS Markdown text into a styled PDF using ReportLab.

This is a lightweight Markdown-to-PDF renderer that handles the subset of
Markdown the agent produces: headings (h1-h3), paragraphs, bold text,
bullet lists, and requirement IDs (FR-001, NFR-001).
"""

import io
import re

from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
)


def _build_styles() -> dict[str, ParagraphStyle]:
    """Create custom paragraph styles for the RS document."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "RSTitle",
            parent=base["Title"],
            fontSize=20,
            spaceAfter=20,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "RSH1",
            parent=base["Heading1"],
            fontSize=16,
            spaceBefore=18,
            spaceAfter=8,
            textColor="#1a1a2e",
        ),
        "h2": ParagraphStyle(
            "RSH2",
            parent=base["Heading2"],
            fontSize=13,
            spaceBefore=14,
            spaceAfter=6,
            textColor="#16213e",
        ),
        "h3": ParagraphStyle(
            "RSH3",
            parent=base["Heading3"],
            fontSize=11,
            spaceBefore=10,
            spaceAfter=4,
            textColor="#0f3460",
        ),
        "body": ParagraphStyle(
            "RSBody",
            parent=base["BodyText"],
            fontSize=10,
            spaceBefore=2,
            spaceAfter=4,
            leading=14,
        ),
        "bullet": ParagraphStyle(
            "RSBullet",
            parent=base["BodyText"],
            fontSize=10,
            spaceBefore=1,
            spaceAfter=2,
            leftIndent=20,
            bulletIndent=10,
            leading=14,
        ),
        "req_id": ParagraphStyle(
            "RSReqId",
            parent=base["BodyText"],
            fontSize=10,
            spaceBefore=4,
            spaceAfter=2,
            leftIndent=10,
            leading=14,
            textColor="#333333",
        ),
    }
    return styles


def _inline_markdown(text: str) -> str:
    """Convert inline markdown (bold, italic) to ReportLab XML tags."""
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    return text


# Pattern for requirement IDs like FR-001, NFR-002
_REQ_ID_PATTERN = re.compile(r"^((?:FR|NFR)-\d{3})")


def _parse_markdown_to_flowables(markdown: str, styles: dict) -> list:
    """Parse RS markdown into ReportLab flowables."""
    flowables = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Title: # Heading
        if line.startswith("# ") and not line.startswith("## "):
            text = _inline_markdown(line[2:].strip())
            flowables.append(Paragraph(text, styles["title"]))
            i += 1
            continue

        # H2: ## Heading
        if line.startswith("## "):
            text = _inline_markdown(line[3:].strip())
            flowables.append(Paragraph(text, styles["h1"]))
            i += 1
            continue

        # H3: ### Heading
        if line.startswith("### "):
            text = _inline_markdown(line[4:].strip())
            flowables.append(Paragraph(text, styles["h2"]))
            i += 1
            continue

        # H4: #### Heading
        if line.startswith("#### "):
            text = _inline_markdown(line[5:].strip())
            flowables.append(Paragraph(text, styles["h3"]))
            i += 1
            continue

        # Bullet list: - item or * item
        if re.match(r"^[\-\*]\s+", line):
            text = _inline_markdown(line.lstrip("-* ").strip())
            flowables.append(
                Paragraph(f"&bull; {text}", styles["bullet"])
            )
            i += 1
            continue

        # Requirement ID lines (FR-001: ..., NFR-001: ...)
        req_match = _REQ_ID_PATTERN.match(line)
        if req_match:
            text = _inline_markdown(line)
            flowables.append(Paragraph(f"<b>{text}</b>" if ":" in text else text, styles["req_id"]))
            i += 1
            continue

        # Regular paragraph — accumulate consecutive non-empty lines
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not re.match(r"^[\-\*]\s+", lines[i]):
            para_lines.append(lines[i].rstrip())
            i += 1

        text = _inline_markdown(" ".join(para_lines))
        flowables.append(Paragraph(text, styles["body"]))

    return flowables


def markdown_to_pdf(markdown: str) -> bytes:
    """Convert an RS Markdown document to a PDF and return the bytes."""
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Requirement Specification",
    )

    styles = _build_styles()
    flowables = _parse_markdown_to_flowables(markdown, styles)

    if not flowables:
        # Produce a single-page PDF with a message
        flowables = [Paragraph("No content to display.", styles["body"])]

    doc.build(flowables)
    return buffer.getvalue()
