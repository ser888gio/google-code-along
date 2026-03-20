"""
Research Agent — Knowledge Base & Past Analyses Retriever.

Responsibility: search two data sources when the orchestrator needs context:
  1. GCS knowledge base  — curated docs: tech guidelines, solution templates,
                            example use cases (e.g. partner helper docx)
  2. Vertex AI Search    — indexed past analyses + knowledge base documents,
                            enables semantic/full-text search across all content
  3. GCS past analyses   — finalizer outputs stored at analyses/{session_id}/
                            (used as fallback if Vertex AI Search is not yet set up)

Triggered: on-demand by the orchestrator when the user's description matches a
           known pattern, or when a reference/comparison to past work is useful.

Returns: structured JSON with relevant findings — the orchestrator synthesizes
         this into natural conversation; raw results are never shown to the user.

Model: Gemini Flash — retrieval + summarization, not deep reasoning.

Bucket layout this agent reads from:
  gs://bucket/
  ├── sessions/{session_id}/          ← user uploads (NOT read by this agent)
  ├── analyses/{session_id}/          ← past finalized analyses (READ by this agent)
  │   └── final_analysis.json
  └── knowledge_base/                 ← curated docs (READ by this agent)
      ├── templates/
      ├── guidelines/
      └── examples/
"""

import json

from config import MODEL_RESEARCH, VERTEX_AI_SEARCH_DATASTORE_ID
from gcs.connector import list_files, read_text
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from logger import get_logger
from prompts.agent import RESEARCH_SYSTEM_PROMPT

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool function 1 — Vertex AI Search
# ---------------------------------------------------------------------------


def search_vertex_ai(query: str, max_results: int = 5) -> dict:
    """Search the Vertex AI Search datastore for documents matching *query*.

    Covers both the curated knowledge base and indexed past analyses.

    Returns:
        {"found": bool, "results": [...]}

    TODO (Google Cloud setup required before hackathon continues):
      1. Go to GCP Console → Vertex AI Search → Create App (Generic / Document search)
      2. Connect it to GCS bucket paths:
           gs://<bucket>/knowledge_base/
           gs://<bucket>/analyses/
      3. Enable periodic re-indexing so new finalizer outputs appear automatically
      4. Copy the datastore ID into .env as VERTEX_AI_SEARCH_DATASTORE_ID
      5. Uncomment implementation below

    TODO (code — implement when datastore is ready):
        from google.cloud import discoveryengine_v1 as discoveryengine
        client = discoveryengine.SearchServiceClient()
        serving_config = (
            f"projects/{GCP_PROJECT}/locations/global/collections/default_collection"
            f"/dataStores/{VERTEX_AI_SEARCH_DATASTORE_ID}/servingConfigs/default_config"
        )
        request = discoveryengine.SearchRequest(
            serving_config=serving_config, query=query, page_size=max_results
        )
        response = client.search(request)
        results = [
            {"title": r.document.name, "snippet": r.document.derived_struct_data.get("snippets", ""),
             "source": r.document.name, "relevance_score": None}
            for r in response.results
        ]
        return {"found": bool(results), "results": results}
    """
    if not VERTEX_AI_SEARCH_DATASTORE_ID:
        logger.warning(
            "Vertex AI Search not configured — VERTEX_AI_SEARCH_DATASTORE_ID missing, falling back to GCS scan"
        )
        return {
            "found": False,
            "results": [],
            "note": "Vertex AI Search not configured (VERTEX_AI_SEARCH_DATASTORE_ID missing)",
        }
    # TODO: implement when datastore is created — see docstring above
    return {
        "found": False,
        "results": [],
        "note": "Vertex AI Search integration pending",
    }


# ---------------------------------------------------------------------------
# Tool function 2 — GCS past analyses fallback
# ---------------------------------------------------------------------------


def search_past_analyses(query: str, max_results: int = 3) -> dict:
    """Scan past finalized analyses stored in GCS and return the most relevant ones.

    Fallback for when Vertex AI Search is not yet configured.
    Reads all analyses/*/final_analysis.json files from GCS and ranks them
    by simple keyword overlap with *query*.

    Returns:
        {
            "found": bool,
            "results": [{"session_id", "use_case_title", "department",
                          "solution_type", "priority_tier", "summary"}, ...]
        }

    TODO: replace keyword scoring with Gemini Flash ranking once there are
          enough past analyses to make it worthwhile.
    TODO: add in-memory cache with TTL to avoid re-reading all GCS files every call.
    """
    try:
        analysis_paths = [
            p
            for p in list_files(prefix="analyses/")
            if p.endswith("final_analysis.json")
        ]
        logger.debug(
            f"Searching past analyses: query='{query}' found={len(analysis_paths)} files"
        )
        if not analysis_paths:
            return {"found": False, "results": []}

        query_tokens = query.lower().split()
        scored: list[tuple[int, dict]] = []

        for path in analysis_paths:
            try:
                data = json.loads(read_text(path))
                form = data.get("use_case_form", {})
                tech = data.get("technology_recommendation", {})
                tier = data.get("priority_tier", {})
                summary_text = f"{form.get('use_case_title', '')} {form.get('department', '')} {form.get('process_as_is', '')} {form.get('purpose_to_be', '')}".lower()
                score = sum(1 for t in query_tokens if t in summary_text)
                scored.append(
                    (
                        score,
                        {
                            "session_id": data.get("_meta", {}).get(
                                "session_id", path.split("/")[1]
                            ),
                            "use_case_title": form.get("use_case_title", ""),
                            "department": form.get("department", ""),
                            "solution_type": form.get(
                                "solution_type", tech.get("primary", "")
                            ),
                            "priority_tier": tier.get("tier", ""),
                            "summary": tech.get("rationale", ""),
                        },
                    )
                )
            except Exception:
                continue

        # Return top matches; if no keywords matched still return all (at most max_results)
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [r for _, r in scored[:max_results]]
        logger.debug(
            f"Past analyses search returned {len(results)} results for query='{query}'"
        )
        return {"found": bool(results), "results": results}

    except Exception as exc:
        logger.warning(f"search_past_analyses failed: {exc}")
        return {"found": False, "results": []}


# ---------------------------------------------------------------------------
# Tool function 3 — GCS knowledge base listing
# ---------------------------------------------------------------------------


def list_knowledge_base_docs() -> dict:
    """List all documents available in the curated knowledge base.

    Returns:
        {
            "categories": {
                "templates":  [str, ...],   # gs:// blob paths
                "guidelines": [str, ...],
                "examples":   [str, ...]
            }
        }

    TODO (manual setup required before hackathon continues):
      Upload curated documents to GCS knowledge_base/ sub-folders:
        gs://<bucket>/knowledge_base/templates/  — IT use case PDF form template
        gs://<bucket>/knowledge_base/guidelines/ — solution type selection guide
                                                   (Power Platform vs SharePoint vs custom app vs SAP)
        gs://<bucket>/knowledge_base/examples/   — "Partner agent helper.docx" converted to text
      Then index those paths in the Vertex AI Search datastore (see search_vertex_ai TODO).
    """
    try:
        return {
            "categories": {
                "templates": list_files(prefix="knowledge_base/templates/"),
                "guidelines": list_files(prefix="knowledge_base/guidelines/"),
                "examples": list_files(prefix="knowledge_base/examples/"),
            }
        }
    except Exception as exc:
        logger.warning(f"list_knowledge_base_docs failed: {exc}")
        return {"categories": {"templates": [], "guidelines": [], "examples": []}}


# ---------------------------------------------------------------------------
# Standalone tool exports — registered directly on the orchestrator in agent.py
# so it can call them without the research sub-agent hop.
# ---------------------------------------------------------------------------

RESEARCH_TOOLS = [
    FunctionTool(func=search_vertex_ai),
    FunctionTool(func=search_past_analyses),
    FunctionTool(func=list_knowledge_base_docs),
]

# ADK Agent definition kept for reference and future multi-agent wiring.
# The demo pipeline uses RESEARCH_TOOLS directly on the orchestrator.
research_agent = Agent(
    name="research_agent",
    description=(
        "Searches the curated knowledge base (GCS + Vertex AI Search) and past "
        "finalized analyses to find similar use cases, technology guidelines, and "
        "reference material relevant to the current discovery session."
    ),
    model=MODEL_RESEARCH,
    instruction=RESEARCH_SYSTEM_PROMPT,
    tools=RESEARCH_TOOLS,
)
