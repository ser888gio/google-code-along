"""
Pytest configuration — installs google.adk stubs before any test module is
imported, so that modules that import google.adk at the top level (compiler,
pdf_export via generation/__init__.py, main.py) can be collected without a
live GCP environment.
"""

import sys
import types
from unittest.mock import MagicMock


def _install_google_adk_stubs():
    """
    Register minimal stub modules for every google.* package that the
    backend imports.  This runs once before test collection starts.
    """
    if "google.adk" in sys.modules:
        return  # already installed (e.g. by a previous conftest run)

    # --- google (namespace package) ---
    google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
    if not hasattr(google_mod, "__path__"):
        google_mod.__path__ = []  # type: ignore[attr-defined]

    # --- google.adk ---
    adk_mod = types.ModuleType("google.adk")
    adk_mod.__path__ = []
    sys.modules["google.adk"] = adk_mod

    # --- google.adk.runners ---
    runners_mod = types.ModuleType("google.adk.runners")
    runners_mod.Runner = MagicMock()
    sys.modules["google.adk.runners"] = runners_mod

    # --- google.adk.sessions ---
    sessions_mod = types.ModuleType("google.adk.sessions")
    # Provide both InMemorySessionService and Session so compiler.py can
    # import them at the module level without error.
    sessions_mod.InMemorySessionService = MagicMock()
    sessions_mod.Session = MagicMock()
    sys.modules["google.adk.sessions"] = sessions_mod

    # --- google.adk.agents ---
    agents_mod = types.ModuleType("google.adk.agents")
    agents_mod.__path__ = []
    agents_mod.Agent = MagicMock()
    sys.modules["google.adk.agents"] = agents_mod

    live_queue_mod = types.ModuleType("google.adk.agents.live_request_queue")
    live_queue_mod.LiveRequestQueue = MagicMock()
    sys.modules["google.adk.agents.live_request_queue"] = live_queue_mod

    run_config_mod = types.ModuleType("google.adk.agents.run_config")
    run_config_mod.RunConfig = MagicMock()
    run_config_mod.StreamingMode = MagicMock()
    run_config_mod.StreamingMode.BIDI = "BIDI"
    sys.modules["google.adk.agents.run_config"] = run_config_mod

    events_mod = types.ModuleType("google.adk.events")
    events_mod.__path__ = []
    event_mod = types.ModuleType("google.adk.events.event")
    event_mod.Event = MagicMock()
    sys.modules["google.adk.events"] = events_mod
    sys.modules["google.adk.events.event"] = event_mod

    # --- google.adk.models.google_llm ---
    models_mod = types.ModuleType("google.adk.models")
    models_mod.__path__ = []
    google_llm_mod = types.ModuleType("google.adk.models.google_llm")

    class _FakeGemini:
        def __init__(self, *args, **kwargs):
            pass

        def _tracking_headers(self):
            return {}

        @property
        def _live_api_version(self):
            return "v1beta"

    google_llm_mod.Gemini = _FakeGemini
    sys.modules["google.adk.models"] = models_mod
    sys.modules["google.adk.models.google_llm"] = google_llm_mod

    # --- google.adk.tools ---
    tools_mod = types.ModuleType("google.adk.tools")
    tools_mod.FunctionTool = MagicMock(
        side_effect=lambda *args, **kwargs: kwargs.get("func") or (args[0] if args else MagicMock())
    )
    sys.modules["google.adk.tools"] = tools_mod

    # --- google.genai ---
    genai_mod = types.ModuleType("google.genai")
    genai_mod.__path__ = []
    genai_mod.Client = MagicMock()
    sys.modules["google.genai"] = genai_mod

    # --- google.genai.types ---
    types_mod = types.ModuleType("google.genai.types")

    class _FakePart:
        def __init__(self, text: str = ""):
            self.text = text

        @staticmethod
        def from_text(text: str = "") -> "_FakePart":
            return _FakePart(text=text)

    class _FakeContent:
        def __init__(self, role: str = "user", parts=None):
            self.role = role
            self.parts = parts or []

    types_mod.Part = _FakePart
    types_mod.Content = _FakeContent
    types_mod.HttpOptions = MagicMock()
    types_mod.AudioTranscriptionConfig = MagicMock()
    types_mod.Blob = MagicMock()
    types_mod.SpeechConfig = MagicMock()
    types_mod.VoiceConfig = MagicMock()
    sys.modules["google.genai.types"] = types_mod
    genai_mod.types = types_mod  # type: ignore[attr-defined]

    errors_mod = types.ModuleType("google.genai.errors")
    errors_mod.APIError = Exception
    sys.modules["google.genai.errors"] = errors_mod

    # --- google.cloud / google.cloud.aiplatform ---
    cloud_mod = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
    if not hasattr(cloud_mod, "__path__"):
        cloud_mod.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google.cloud.aiplatform"] = types.ModuleType("google.cloud.aiplatform")

    firestore_mod = types.ModuleType("google.cloud.firestore")
    firestore_mod.Client = MagicMock()
    firestore_mod.ArrayUnion = MagicMock(side_effect=lambda value: value)
    sys.modules["google.cloud.firestore"] = firestore_mod
    cloud_mod.firestore = firestore_mod  # type: ignore[attr-defined]


# Run immediately when conftest is loaded (before collection)
_install_google_adk_stubs()
