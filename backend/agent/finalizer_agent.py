"""
Finalizer Agent — Use Case Analysis & Classification.

Responsibility: produce the complete final analysis document once the discovery
session reaches ≥ 90% completeness. This is the last step in the pipeline.

Triggered: by main.py as a background asyncio.Task when the orchestrator outputs
           the [FINALIZING] marker in its streamed response.

Input context assembled by the backend before calling the agent:
  - Full conversation transcript (from ADK session)
  - All 22 discovered fields (from discovery_agent / extract_discovery_fields)
  - User-uploaded files list + content from GCS sessions/{session_id}/
  - Research results cached from research_agent calls during the session
  - Relevant past analyses from Vertex AI Search / GCS analyses/

Output:
  - final_analysis.json written to GCS at analyses/{session_id}/final_analysis.json
  - Firestore document updated with finalization_status and all output fields
  - SSE event "finalizing_complete" signalled to frontend via a shared status dict
    (or Firestore polling — see TODO below)

Model: Gemini Pro — deep synthesis across multiple sources, structured JSON output.

Bucket layout this agent writes to:
  gs://bucket/
  └── analyses/
      └── {session_id}/
          ├── final_analysis.json    ← main output (written by this agent)
          └── final_analysis.docx   ← TODO: generated from JSON (nice-to-have)
"""

from google.adk.agents import Agent

# TODO: import FunctionTool from google.adk.tools
# from google.adk.tools import FunctionTool
from .prompt import FINALIZER_SYSTEM_PROMPT

FINALIZER_MODEL = "gemini-2.5-pro-preview-05-06"

# TODO: register tools once implemented:
#
#   tools=[
#       FunctionTool(func=read_session_uploads),
#       FunctionTool(func=save_final_analysis),
#   ]
#
# The agent calls read_session_uploads to ingest user files, then uses
# save_final_analysis to persist its output once generation is complete.

finalizer_agent = Agent(
    name="finalizer_agent",
    description=(
        "Synthesizes all collected context from a discovery session into a complete "
        "IT use case analysis with technology recommendation, team profile, priority "
        "tier classification, and risk assessment. Stores the result to GCS."
    ),
    model=FINALIZER_MODEL,
    instruction=FINALIZER_SYSTEM_PROMPT,
    tools=[],  # TODO: replace with [FunctionTool(read_session_uploads), FunctionTool(save_final_analysis)]
)


# ---------------------------------------------------------------------------
# Main entry point — called from main.py as a background task
# ---------------------------------------------------------------------------


async def run_finalizer(
    session_id: str,
    user_id: str,
    conversation_text: str,
    discovery_fields: dict,
    research_context: str | None = None,
) -> dict | None:
    """Run the full finalization pipeline for a session.

    Called by main.py as an asyncio background task when [FINALIZING] is detected.
    Writes the result to GCS and Firestore, then signals completion.

    Args:
        session_id:        ADK session ID.
        user_id:           User ID (used for Firestore status update).
        conversation_text: Full conversation transcript (flat text).
        discovery_fields:  Dict of 22 fields from extract_discovery_fields().
        research_context:  Optional string with research_agent results from this session.

    Returns:
        The final analysis dict, or None on failure.

    TODO: implement the full pipeline:
      1. Call read_session_uploads(session_id) to get list + content of uploaded files
      2. Assemble the full input context string (conversation + fields + files + research)
      3. Run the finalizer_agent via the ADK runner (or call Gemini Pro directly —
         see note below about ADK vs direct API for background tasks)
      4. Parse and validate the JSON output from the agent
      5. Call save_final_analysis(session_id, result) to write to GCS
      6. Call upsert_final_analysis_to_firestore(session_id, result) to update Firestore
      7. Signal completion so frontend stops showing "finalizing" state

    Note on ADK vs direct Gemini call:
      The finalizer runs in a background task, outside the main ADK runner loop.
      Options:
        A) Create a separate ADK Runner for the finalizer with its own session —
           cleanest if you want full ADK tool support (file reading, saving)
        B) Call Gemini Pro directly via vertexai.GenerativeModel, pass all context
           in a single large prompt — simpler, avoids ADK session complexity
      TODO: decide approach. Option B is recommended for the hackathon given time constraints.
    """
    # TODO: implement
    raise NotImplementedError("TODO: implement run_finalizer()")


# ---------------------------------------------------------------------------
# Tool function 1 — Read user-uploaded session files
# ---------------------------------------------------------------------------


async def read_session_uploads(session_id: str) -> dict:
    """Read all files the user uploaded during the session from GCS.

    Args:
        session_id: The session ID to read uploads for.

    Returns:
        {
            "files": [
                {
                    "filename": str,
                    "gcs_path": str,           # gs://bucket/sessions/{id}/{name}
                    "content_type": str,
                    "text_content": str | null  # extracted text, null for non-text files
                },
                ...
            ]
        }

    TODO: implement using gcs.connector.list_files() and read_text() / read_file().
          Path prefix: sessions/{session_id}/

    TODO: for non-text files (PDF, DOCX), add text extraction so the finalizer
          can read their content:
            - PDF: use reportlab / pypdf to extract text
            - DOCX: use python-docx to extract paragraphs
            - Excel: skip for now, note as attachment only
          If text extraction fails, include the file as metadata-only (filename + path).

    TODO: add a size guard — skip files > 500KB to avoid exceeding Gemini context limits.
          Log a warning when a file is skipped.
    """
    # TODO: implement
    #
    # from gcs import list_files, read_file, read_text
    #
    # paths = list_files(prefix=f"sessions/{session_id}/")
    # files = []
    # for path in paths:
    #     filename = path.split("/")[-1]
    #     text = None
    #     try:
    #         if filename.endswith((".txt", ".md", ".json", ".csv")):
    #             text = read_text(path)
    #         elif filename.endswith(".pdf"):
    #             pass  # TODO: extract text from PDF
    #         elif filename.endswith(".docx"):
    #             pass  # TODO: extract text from DOCX
    #     except Exception:
    #         pass
    #     files.append({"filename": filename, "gcs_path": f"gs://...", "text_content": text})
    # return {"files": files}

    raise NotImplementedError("TODO: implement read_session_uploads()")


# ---------------------------------------------------------------------------
# Tool function 2 — Save final analysis to GCS
# ---------------------------------------------------------------------------


async def save_final_analysis(session_id: str, analysis: dict) -> str:
    """Write the final analysis JSON to GCS.

    Args:
        session_id: The session this analysis belongs to.
        analysis:   The complete final analysis dict produced by the agent.

    Returns:
        The gs:// URI of the saved file.

    TODO: implement using gcs.connector.write_file().
          Target path: analyses/{session_id}/final_analysis.json

    TODO: also generate a DOCX version (nice-to-have):
          Use a Word template populated with the analysis sections.
          Target path: analyses/{session_id}/final_analysis.docx
    """
    # TODO: implement
    #
    # import json
    # from gcs import write_file
    #
    # path = f"analyses/{session_id}/final_analysis.json"
    # data = json.dumps(analysis, ensure_ascii=False, indent=2)
    # return write_file(path=path, data=data, content_type="application/json")

    raise NotImplementedError("TODO: implement save_final_analysis()")


# ---------------------------------------------------------------------------
# Firestore update — persist final analysis status and output
# ---------------------------------------------------------------------------


def upsert_final_analysis_to_firestore(session_id: str, analysis: dict) -> None:
    """Persist the finalization result and status to Firestore.

    Writes two things:
      1. finalization_status: "complete" + timestamp — lets the frontend stop polling
      2. All 22 form field values from use_case_form — replaces the partial live values
         stored by the old context extractor, now with the finalizer's cleaned-up values

    Args:
        session_id: The session ID.
        analysis:   The complete final analysis dict.

    TODO: implement using firestore.writer._client() pattern.
          This should be a merge write (set(..., merge=True)) — never erase prior data.

    TODO: add a finalization_status field to the Firestore schema:
          "finalization_status": "pending" | "complete" | "error"
          "finalized_at": ISO timestamp
          This is what the frontend polls to know when to show the result panel.

    TODO: update firestore/writer.py to add:
          - upsert_final_analysis(session_id, analysis) function
          - get_final_analysis(session_id) function — returns the full analysis or None
          The writer.py currently only handles 8 SRS fields; it needs the new 22-field
          schema + finalization_status field.

    TODO: decide whether to store the full classification output (tech recommendation,
          team profile, priority tier) in Firestore as well, or only point to GCS.
          Recommendation: store key classification fields in Firestore (fast reads for
          the frontend summary panel) and store the full JSON in GCS (for downloads).
    """
    # TODO: implement
    raise NotImplementedError("TODO: implement upsert_final_analysis_to_firestore()")


# ---------------------------------------------------------------------------
# Output schema reference (mirrors FINALIZER_SYSTEM_PROMPT)
# ---------------------------------------------------------------------------
# Kept here as a Python dict for use in validation and frontend type generation.
# TODO: generate TypeScript types for the frontend from this schema.

FINAL_ANALYSIS_SCHEMA = {
    "use_case_form": {
        # All 22 fields from FIELD_SCHEMA in discovery_agent.py
        # Populated by the finalizer, TBD for any truly unknown fields
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
        "open_questions": list,  # things not confirmed during discovery
    },
    # Metadata added by the backend (not by the agent)
    "_meta": {
        "session_id": str,
        "finalized_at": str,  # ISO timestamp
        "model": str,  # model used for generation
        "discovery_completeness": int,  # score at the time of finalization
    },
}
