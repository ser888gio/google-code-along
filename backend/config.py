import os
import re

from dotenv import load_dotenv

load_dotenv()
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"

GCP_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")

_GCP_REGION_RAW: str = os.getenv("GOOGLE_CLOUD_REGION", "")
# Strip zone suffix: "europe-central2-a" → "europe-central2"
GCP_REGION: str = "-".join(_GCP_REGION_RAW.split("-")[:3])

GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "")

# GCS path prefixes (used when constructing blob paths throughout the app)
GCS_PREFIX_SESSIONS = "sessions"  # sessions/{session_id}/{filename}
GCS_PREFIX_ANALYSES = "analyses"  # analyses/{session_id}/final_analysis.json
GCS_PREFIX_KNOWLEDGE_BASE = "knowledge_base"  # knowledge_base/{category}/

FIRESTORE_COLLECTION: str = os.getenv("FIRESTORE_COLLECTION", "")
FIRESTORE_DATABASE: str = os.getenv("FIRESTORE_DATABASE", "")


VERTEX_AI_SEARCH_DATASTORE_ID: str | None = os.getenv("VERTEX_AI_SEARCH_DATASTORE_ID")

# Audio model for bidirectional voice streaming via Live API
MODEL_AUDIO = "gemini-live-2.5-flash-native-audio"

# Region for the Live API (may differ from GOOGLE_CLOUD_REGION)
AUDIO_REGION = os.getenv("GOOGLE_CLOUD_AUDIO_REGION", "europe-west1")

# Orchestrator: strong reasoning, drives the discovery conversation
MODEL_ORCHESTRATOR = "gemini-3.1-pro-preview"

# Finalizer: deep synthesis across multiple sources → structured JSON
MODEL_FINALIZER = "gemini-3.1-pro-preview"

# Discovery tracker: fast extraction after every user message
MODEL_DISCOVERY = "gemini-3.1-pro-preview"

# Research agent: retrieval + summarisation, no deep reasoning needed
MODEL_RESEARCH = "gemini-3.1-pro-preview"

# Legacy 8-field RS context extractor
MODEL_CONTEXT = "gemini-3.1-pro-preview"

# BPMN / DataFlow diagram generation
MODEL_BPMN = "gemini-3.1-pro-preview"
MODEL_DATAFLOW = "gemini-3.1-pro-preview"

# SRS document compiler (legacy Word export pipeline)
MODEL_SRS_COMPILER = "gemini-3.1-pro-preview"

# ADK runner app name — used in InMemorySessionService calls
APP_NAME = "rs_generator"

# Markers emitted by agents and handled / stripped by the backend
FINALIZING_MARKER = "[FINALIZING]"
RS_MARKER = "[GENERATE_RS]"

# Regex pattern for requirement IDs like FR-001, NFR-002 (used in PDF renderer)
REQ_ID_PATTERN: re.Pattern = re.compile(r"^((?:FR|NFR)-\d{3})")

# File extensions treated as readable plain text when the finalizer reads uploads
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".json", ".csv"})


def init_vertex_ai() -> None:
    """Initialise the Vertex AI SDK with the configured project and region.

    Safe to call multiple times — subsequent calls are no-ops within the same process.
    Call this once at the top of any function that creates a GenerativeModel.
    """
    import vertexai  # local import to avoid pulling vertexai into pure-config tests

    vertexai.init(project=GCP_PROJECT, location="global")
