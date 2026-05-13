import os
import re

from dotenv import load_dotenv

load_dotenv()

# Use Gemini API key — disable Vertex AI mode for the google-genai / ADK SDK
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

GCP_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")

GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "")

# GCS path prefixes (used when constructing blob paths throughout the app)
GCS_PREFIX_SESSIONS = "sessions"  # sessions/{session_id}/{filename}
GCS_PREFIX_ANALYSES = "analyses"  # analyses/{session_id}/final_analysis.json
GCS_PREFIX_KNOWLEDGE_BASE = "knowledge_base"  # knowledge_base/{category}/

FIRESTORE_COLLECTION: str = os.getenv("FIRESTORE_COLLECTION", "")
FIRESTORE_DATABASE: str = os.getenv("FIRESTORE_DATABASE", "")

ADMIN_BEARER_TOKEN: str = os.getenv("ADMIN_BEARER_TOKEN", "")
BIGQUERY_DATASET: str = os.getenv("BIGQUERY_DATASET", "observability")
BIGQUERY_MESSAGES_VIEW: str = os.getenv(
    "BIGQUERY_MESSAGES_VIEW",
    f"{GCP_PROJECT}.{BIGQUERY_DATASET}.messages" if GCP_PROJECT else "",
)
BIGQUERY_FEEDBACK_VIEW: str = os.getenv(
    "BIGQUERY_FEEDBACK_VIEW",
    f"{GCP_PROJECT}.{BIGQUERY_DATASET}.feedback" if GCP_PROJECT else "",
)
COST_CIRCUIT_BREAKER_USD: float = float(
    os.getenv("COST_CIRCUIT_BREAKER_USD", "5.0")
)

APP_ENV: str = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower()
_PRODUCTION_ENVS = {"production", "prod", "staging"}
_LOCAL_OPTIONAL_CONFIG = {
    "GCP_PROJECT",
    "GCS_BUCKET_NAME",
    "FIRESTORE_COLLECTION",
    "FIRESTORE_DATABASE",
}
_PRODUCTION_REQUIRED_CONFIG = {
    "GOOGLE_API_KEY": GOOGLE_API_KEY,
    "GCP_PROJECT": GCP_PROJECT,
    "GCS_BUCKET_NAME": GCS_BUCKET_NAME,
    "FIRESTORE_COLLECTION": FIRESTORE_COLLECTION,
    "FIRESTORE_DATABASE": FIRESTORE_DATABASE,
}


def require_config_value(name: str, value: str | None, usage: str) -> str:
    """Return a stripped config value or raise a clear setup error."""
    resolved = (value or "").strip()
    if not resolved:
        raise RuntimeError(f"{name} is not configured; set {name} before {usage}.")
    return resolved


def validate_config(*, strict: bool | None = None) -> list[str]:
    """Validate runtime config and return dev-mode warnings.

    Production/staging requires all cloud config. Local development only requires
    GOOGLE_API_KEY at startup; cloud-only settings fail clearly when those
    integrations are used.
    """
    is_strict = APP_ENV in _PRODUCTION_ENVS if strict is None else strict
    required = dict(_PRODUCTION_REQUIRED_CONFIG)
    if not is_strict:
        required = {"GOOGLE_API_KEY": GOOGLE_API_KEY}

    missing = [name for name, value in required.items() if not (value or "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(sorted(missing))
            + ". Set the corresponding environment variables before startup."
        )

    if is_strict:
        return []

    return [
        f"{name} is not set; related cloud integration endpoints will fail until configured."
        for name in sorted(_LOCAL_OPTIONAL_CONFIG)
        if not (_PRODUCTION_REQUIRED_CONFIG[name] or "").strip()
    ]


# Audio model for bidirectional voice streaming via Live API
MODEL_AUDIO = "gemini-3.1-flash-live-preview"

# Region for the Live API
AUDIO_REGION = os.getenv("GOOGLE_CLOUD_AUDIO_REGION", "europe-west1")

# Orchestrator: strong reasoning, drives the discovery conversation
MODEL_ORCHESTRATOR = "gemini-3.1-pro-preview"

# Finalizer: deep synthesis across multiple sources → structured JSON
MODEL_FINALIZER = "gemini-3.1-pro-preview"

# Discovery tracker: fast extraction after every user message
MODEL_DISCOVERY = "gemini-3.1-flash-lite"

# Research agent: retrieval + summarisation, no deep reasoning needed
MODEL_RESEARCH = "gemini-3.1-flash-lite"

# BPMN / DataFlow diagram generation
MODEL_BPMN = "gemini-3.1-flash-lite"
MODEL_DATAFLOW = "gemini-3.1-flash-lite"

# SRS document compiler (legacy Word export pipeline)
MODEL_SRS_COMPILER = "gemini-3.1-flash-lite"

# ADK runner app name — used in InMemorySessionService calls
APP_NAME = "rs_generator"

# Markers emitted by agents and handled / stripped by the backend
FINALIZING_MARKER = "[FINALIZING]"
RS_MARKER = "[GENERATE_RS]"

# Regex pattern for requirement IDs like FR-001, NFR-002 (used in PDF renderer)
REQ_ID_PATTERN: re.Pattern = re.compile(r"^((?:FR|NFR)-\d{3})")

# File extensions treated as readable plain text when the finalizer reads uploads
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".json", ".csv"})
