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

from google.adk.agents import Agent

# TODO: import FunctionTool from google.adk.tools to register GCS and Vertex AI
#       search functions as callable tools for this agent
# from google.adk.tools import FunctionTool
from .prompt import RESEARCH_SYSTEM_PROMPT

RESEARCH_MODEL = "gemini-2.0-flash-001"

# TODO: define the two tool functions below, then register them:
#
#   tools=[
#       FunctionTool(func=search_knowledge_base),
#       FunctionTool(func=search_past_analyses),
#   ]
#
# Until tools are wired, the agent falls back to prompt-only reasoning,
# which will produce no real results — that is acceptable during development.

research_agent = Agent(
    name="research_agent",
    description=(
        "Searches the curated knowledge base (GCS + Vertex AI Search) and past "
        "finalized analyses to find similar use cases, technology guidelines, and "
        "reference material relevant to the current discovery session."
    ),
    model=RESEARCH_MODEL,
    instruction=RESEARCH_SYSTEM_PROMPT,
    tools=[],  # TODO: replace with [FunctionTool(search_knowledge_base), FunctionTool(search_past_analyses)]
)


# ---------------------------------------------------------------------------
# Tool function 1 — Vertex AI Search
# ---------------------------------------------------------------------------


async def search_vertex_ai(query: str, max_results: int = 5) -> dict:
    """Search the Vertex AI Search datastore for documents matching *query*.

    Covers both the curated knowledge base and indexed past analyses
    (depends on what is configured in the datastore).

    Args:
        query: Natural language search query from the agent.
        max_results: Maximum number of results to return (default 5).

    Returns:
        {
            "found": bool,
            "results": [
                {
                    "title": str,
                    "snippet": str,       # relevant excerpt
                    "source": str,        # document URI or title
                    "relevance_score": float | null
                },
                ...
            ]
        }

    TODO: implement using google-cloud-discoveryengine (Discovery Engine SDK)
          or google.cloud.discoveryengine_v1 client library.
          The datastore ID comes from env var VERTEX_AI_SEARCH_DATASTORE_ID.

    TODO: the datastore must be created in GCP Console first and documents indexed.
          Suggested setup:
            - Create a Vertex AI Search app (type: Generic / Document search)
            - Point it at the GCS bucket path gs://bucket/knowledge_base/
            - Enable periodic re-indexing so new finalized analyses appear automatically
            - Store the datastore ID in .env as VERTEX_AI_SEARCH_DATASTORE_ID

    TODO: handle the case where VERTEX_AI_SEARCH_DATASTORE_ID is not set —
          log a warning and return {"found": False, "results": []} rather than raising.
    """
    # TODO: implement
    #
    # import os
    # from google.cloud import discoveryengine_v1 as discoveryengine
    #
    # datastore_id = os.getenv("VERTEX_AI_SEARCH_DATASTORE_ID")
    # if not datastore_id:
    #     return {"found": False, "results": []}
    #
    # project = os.getenv("GOOGLE_CLOUD_PROJECT")
    # client = discoveryengine.SearchServiceClient()
    # serving_config = (
    #     f"projects/{project}/locations/global/collections/default_collection"
    #     f"/dataStores/{datastore_id}/servingConfigs/default_config"
    # )
    # request = discoveryengine.SearchRequest(
    #     serving_config=serving_config,
    #     query=query,
    #     page_size=max_results,
    # )
    # response = client.search(request)
    # results = [...]  # parse response.results
    # return {"found": bool(results), "results": results}

    raise NotImplementedError("TODO: implement search_vertex_ai()")


# ---------------------------------------------------------------------------
# Tool function 2 — GCS past analyses fallback
# ---------------------------------------------------------------------------


async def search_past_analyses(query: str, max_results: int = 3) -> dict:
    """Scan past finalized analyses stored in GCS and return the most relevant ones.

    This is a fallback for when Vertex AI Search is not yet configured.
    It reads all final_analysis.json files under analyses/ and does a simple
    keyword/field match against the query.

    Args:
        query: Topic or description to match against past analyses.
        max_results: Maximum number of analyses to return (default 3).

    Returns:
        {
            "found": bool,
            "results": [
                {
                    "session_id": str,
                    "use_case_title": str,
                    "department": str,
                    "solution_type": str,
                    "priority_tier": str,
                    "summary": str        # brief description from the analysis
                },
                ...
            ]
        }

    TODO: implement using existing gcs.connector functions (list_files, read_text).
          Path pattern: analyses/{session_id}/final_analysis.json
          Parse each JSON, extract key fields, score relevance against query
          (simple keyword overlap or ask Gemini Flash to rank them).

    TODO: add result caching (e.g. in-memory dict with TTL) to avoid re-reading
          all GCS files on every call — the number of analyses will grow over time.
    """
    # TODO: implement
    #
    # from gcs import list_files, read_text
    # import json
    #
    # analysis_paths = list_files(prefix="analyses/")
    # analysis_paths = [p for p in analysis_paths if p.endswith("final_analysis.json")]
    #
    # candidates = []
    # for path in analysis_paths:
    #     try:
    #         raw = read_text(path)
    #         data = json.loads(raw)
    #         candidates.append(data)
    #     except Exception:
    #         continue
    #
    # # TODO: rank candidates by relevance to query
    # # Simple approach: check if query keywords appear in use_case_title or department
    # # Better approach: pass candidates to Gemini Flash and ask it to rank by relevance
    #
    # return {"found": bool(candidates), "results": candidates[:max_results]}

    raise NotImplementedError("TODO: implement search_past_analyses()")


# ---------------------------------------------------------------------------
# Tool function 3 — GCS knowledge base listing
# ---------------------------------------------------------------------------


async def list_knowledge_base_docs() -> dict:
    """List all documents available in the curated knowledge base.

    Used by the research agent to know what reference material exists before
    deciding which documents to read.

    Returns:
        {
            "categories": {
                "templates": [str, ...],    # gs:// paths
                "guidelines": [str, ...],
                "examples": [str, ...]
            }
        }

    TODO: implement using gcs.connector.list_files().
          Knowledge base path: knowledge_base/{category}/{filename}

    TODO: decide the initial seeding strategy for the knowledge base:
          - Upload the "Partner agent helper.docx" as an example use case
          - Upload solution type guidelines (Power Platform vs SharePoint vs custom app)
          - Upload the IT use case PDF form template
          These should be uploaded to gs://bucket/knowledge_base/ and indexed
          in Vertex AI Search.
    """
    # TODO: implement
    #
    # from gcs import list_files
    # return {
    #     "categories": {
    #         "templates":  list_files(prefix="knowledge_base/templates/"),
    #         "guidelines": list_files(prefix="knowledge_base/guidelines/"),
    #         "examples":   list_files(prefix="knowledge_base/examples/"),
    #     }
    # }

    raise NotImplementedError("TODO: implement list_knowledge_base_docs()")
