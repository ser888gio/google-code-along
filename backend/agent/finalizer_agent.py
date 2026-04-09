"""
Finalizer Agent — Use Case Analysis & Classification.

Responsibility: produce the complete final analysis document once the discovery
session reaches ≥ 90% completeness. This is the last step in the pipeline.

Triggered: by main.py as an asyncio.Task when the orchestrator outputs the
           [FINALIZING] marker in its streamed response.

Input assembled by run_finalizer() before calling Gemini Pro:
  - Full conversation transcript (from ADK session events)
  - All 22 discovered fields (from extract_discovery_fields())
  - User-uploaded files list + content from GCS sessions/{session_id}/
  - Research results cached from research tool calls during the session

Output:
  - final_analysis.json written to GCS at analyses/{session_id}/final_analysis.json
  - Firestore document updated with finalization_status="complete" and full JSON blob
  - Frontend polls GET /analyses/{session_id} to detect completion

Model: Gemini Pro — deep synthesis across multiple sources, structured JSON output.

Bucket layout this agent writes to:
  gs://bucket/
  └── analyses/
      └── {session_id}/
          └── final_analysis.json    ← main output (written by save_final_analysis)

TODO (nice-to-have): generate final_analysis.docx from the JSON using a Word template.
"""

import asyncio
import datetime
import json
import os
import time

import google.generativeai as genai

from config import GOOGLE_API_KEY, MODEL_FINALIZER, TEXT_EXTENSIONS
from firestore.writer import (
    set_finalization_error,
    upsert_final_analysis,
)
from gcs.connector import BUCKET_NAME, list_files, read_file, write_file
from google.adk.agents import Agent
from logger import get_logger
from prompts.agent import FINALIZER_SYSTEM_PROMPT

genai.configure(api_key=GOOGLE_API_KEY)

logger = get_logger(__name__)

# The ADK Agent definition is kept for reference and future ADK-native multi-agent
# wiring.  The actual demo pipeline uses run_finalizer() with a direct Gemini call
# (Option B from the architecture notes) because it runs as a background asyncio.Task
# outside the main ADK runner loop.
finalizer_agent = Agent(
    name="finalizer_agent",
    description=(
        "Synthesizes all collected context from a discovery session into a complete "
        "IT use case analysis with technology recommendation, team profile, priority "
        "tier classification, and risk assessment. Stores the result to GCS."
    ),
    model=MODEL_FINALIZER,
    instruction=FINALIZER_SYSTEM_PROMPT,
    tools=[],
)


# ---------------------------------------------------------------------------
# Main entry point — called from main.py as an asyncio background task
# ---------------------------------------------------------------------------


async def run_finalizer(
    session_id: str,
    user_id: str,
    conversation_text: str,
    discovery_fields: dict,
    research_context: str | None = None,
) -> dict | None:
    """Run the full finalization pipeline for a session.

    Called by main.py as asyncio.create_task() when [FINALIZING] is detected.
    Writes the result to GCS and Firestore.

    Args:
        session_id:        ADK session ID.
        user_id:           User ID (for logging; Firestore update uses session_id only).
        conversation_text: Full conversation transcript as plain text.
        discovery_fields:  Output of extract_discovery_fields() — 22-field dict.
        research_context:  Optional string with research results from this session.

    Returns:
        The final analysis dict on success, or None on failure.
    """

    logger.info(
        f"Finalizer started: session_id={session_id} discovery_completeness={discovery_fields.get('completeness')}%"
    )
    try:
        # 1. Read user-uploaded files from GCS (text files only; others noted by name)
        try:
            uploads = await read_session_uploads(session_id)
            file_count = len(uploads.get("files", []))
            logger.debug(
                f"Session uploads loaded: session_id={session_id} files={file_count}"
            )
        except Exception as exc:
            logger.warning(
                f"read_session_uploads failed (continuing without): session_id={session_id} error={exc}"
            )
            uploads = {"files": []}

        # 2. Assemble the full input context for the model
        files_section = ""
        for f in uploads.get("files", []):
            name = f.get("filename", "?")
            content = f.get("text_content")
            if content:
                files_section += f"\n\n--- Uploaded file: {name} ---\n{content}"
            else:
                files_section += (
                    f"\n\n--- Uploaded file (binary, not readable): {name} ---"
                )

        context_parts = [
            f"## Conversation Transcript\n{conversation_text}",
            f"## Extracted Form Fields (22 fields)\n{json.dumps(discovery_fields, ensure_ascii=False, indent=2)}",
        ]
        if research_context:
            context_parts.append(
                f"## Research Context (from knowledge base / past analyses)\n{research_context}"
            )
        if files_section:
            context_parts.append(f"## User-Uploaded Files\n{files_section}")

        full_context = "\n\n".join(context_parts)
        prompt = f"{FINALIZER_SYSTEM_PROMPT}\n\n{full_context}"

        # 3. Call Gemini Pro directly (not via ADK runner — background task, no ADK session)
        logger.debug(
            f"Calling Gemini model={MODEL_FINALIZER} for final analysis: session_id={session_id}"
        )
        model = genai.GenerativeModel(MODEL_FINALIZER)

        # Run blocking generate_content() in a thread so we don't freeze the event loop
        logger.info(
            f"Model call started: model={MODEL_FINALIZER} caller=run_finalizer session_id={session_id}"
        )
        _t0 = time.perf_counter()
        response = await asyncio.to_thread(model.generate_content, prompt)
        logger.info(
            f"Model call completed: model={MODEL_FINALIZER} elapsed={time.perf_counter() - _t0:.2f}s session_id={session_id}"
        )

        # 4. Parse JSON output
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        result = json.loads(raw)

        # 5. Attach server-side metadata
        result["_meta"] = {
            "session_id": session_id,
            "finalized_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "model": MODEL_FINALIZER,
            "discovery_completeness": discovery_fields.get("completeness", 0),
        }

        # 6. Save full JSON to GCS — analyses/{session_id}/final_analysis.json
        await save_final_analysis(session_id, result)

        # 7. Update Firestore — sets finalization_status="complete" + stores JSON
        await asyncio.to_thread(upsert_final_analysis, session_id, result)

        logger.info(f"Finalizer complete: session_id={session_id}")
        return result

    except Exception as exc:
        logger.error(f"Finalizer failed: session_id={session_id} error={exc}")
        try:
            await asyncio.to_thread(set_finalization_error, session_id)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Tool function 1 — Read user-uploaded session files from GCS
# ---------------------------------------------------------------------------


async def read_session_uploads(session_id: str) -> dict:
    """Read all files the user uploaded during the session from GCS.

    Extracts text content from .txt / .md / .json / .csv files.
    Binary files (PDF, DOCX, images) are listed by name only.

    Returns:
        {
            "files": [
                {
                    "filename":     str,
                    "gcs_path":     str,           # gs://bucket/sessions/{id}/{name}
                    "text_content": str | null     # extracted text, null for binary
                },
                ...
            ]
        }

    TODO: add PDF text extraction using pypdf:
          from pypdf import PdfReader; import io
          reader = PdfReader(io.BytesIO(raw_bytes))
          text = "\\n".join(page.extract_text() for page in reader.pages)

    TODO: add DOCX text extraction using python-docx:
          from docx import Document; import io
          doc = Document(io.BytesIO(raw_bytes))
          text = "\\n".join(p.text for p in doc.paragraphs)

    TODO: skip files > 500 KB to stay within Gemini context limits.
    """

    prefix = f"sessions/{session_id}/"
    paths = list_files(prefix=prefix)

    files = []
    for path in paths:
        filename = path.split("/")[-1]
        if not filename:
            continue
        gcs_path = f"gs://{BUCKET_NAME}/{path}"
        text_content = None
        ext = os.path.splitext(filename)[1].lower()
        try:
            if ext in TEXT_EXTENSIONS:
                raw = read_file(path)
                text_content = raw.decode("utf-8", errors="replace")
            # TODO: handle PDF / DOCX — see docstring above
        except Exception as exc:
            logger.warning(f"Could not read uploaded file: path={path} error={exc}")
        files.append(
            {"filename": filename, "gcs_path": gcs_path, "text_content": text_content}
        )

    return {"files": files}


# ---------------------------------------------------------------------------
# Tool function 2 — Save final analysis JSON to GCS
# ---------------------------------------------------------------------------


async def save_final_analysis(session_id: str, analysis: dict) -> str:
    """Write the final analysis JSON to GCS.

    Args:
        session_id: The session this analysis belongs to.
        analysis:   The complete final analysis dict produced by the model.

    Returns:
        The gs:// URI of the saved file.

    TODO (nice-to-have): also generate a DOCX version populated from the JSON.
          Use python-docx with a Word template.
          Target: analyses/{session_id}/final_analysis.docx
    """

    path = f"analyses/{session_id}/final_analysis.json"
    data = json.dumps(analysis, ensure_ascii=False, indent=2)
    gcs_uri = await asyncio.to_thread(write_file, path, data, "application/json")
    logger.info(f"Final analysis saved to GCS: {gcs_uri}")
    return gcs_uri


# ---------------------------------------------------------------------------
# Firestore update — called from run_finalizer() after GCS write
# ---------------------------------------------------------------------------


def upsert_final_analysis_to_firestore(session_id: str, analysis: dict) -> None:
    """Thin wrapper — delegates to firestore.writer.upsert_final_analysis().

    Kept as a named function here so it can be imported by tests
    and called directly if needed outside run_finalizer().
    """

    upsert_final_analysis(session_id, analysis)


# ---------------------------------------------------------------------------
# Output schema reference (mirrors FINALIZER_SYSTEM_PROMPT)
# ---------------------------------------------------------------------------
# Kept here as a Python dict for validation reference.
# TODO: generate TypeScript types for the frontend from this schema automatically.

FINAL_ANALYSIS_SCHEMA = {
    "use_case_form": {
        # All 22 fields from FIELD_SCHEMA in discovery_agent.py
    },
    "technology_recommendation": {
        "primary": str,  # e.g. "Microsoft Power Platform"
        "rationale": str,  # 2-3 sentences
        "alternatives": list,  # 1-2 options
        "constraints": list,  # known blockers or risks
    },
    "team_profile": {
        "recommended_team_type": str,  # "internal" | "partner" | "vendor" | "mixed"
        "skills_required": list,
        "rationale": str,
    },
    "priority_tier": {
        "tier": str,  # "strategic" | "tactical" | "operational"
        "score": int,  # 0-100 weighted score
        "scoring_rationale": str,
        "priority_drivers": list,  # top reasons for the tier
    },
    "risk_and_dependencies": {
        "risks": list,
        "dependencies": list,
        "open_questions": list,
    },
    # Metadata added by run_finalizer() (not by the model)
    "_meta": {
        "session_id": str,
        "finalized_at": str,  # ISO timestamp
        "model": str,
        "discovery_completeness": int,  # score at time of finalization
    },
}
