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

# Audio model for bidirectional voice streaming via Live API
MODEL_AUDIO = "gemini-3.1-flash-live-preview"

# Region for the Live API
AUDIO_REGION = os.getenv("GOOGLE_CLOUD_AUDIO_REGION", "europe-west1")

# Orchestrator: strong reasoning, drives the discovery conversation
MODEL_ORCHESTRATOR = "gemini-3.1-pro-preview"

# Finalizer: deep synthesis across multiple sources → structured JSON
MODEL_FINALIZER = "gemini-3.1-pro-preview"

# Discovery tracker: fast extraction after every user message
MODEL_DISCOVERY = "gemini-3.1-pro-preview"

# Research agent: retrieval + summarisation, no deep reasoning needed
MODEL_RESEARCH = "gemini-3.1-pro-preview"

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
