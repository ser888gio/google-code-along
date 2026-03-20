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
    agents_mod.Agent = MagicMock()
    sys.modules["google.adk.agents"] = agents_mod

    # --- google.genai ---
    genai_mod = types.ModuleType("google.genai")
    genai_mod.__path__ = []
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
    sys.modules["google.genai.types"] = types_mod
    genai_mod.types = types_mod  # type: ignore[attr-defined]

    # --- google.cloud / google.cloud.aiplatform ---
    cloud_mod = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
    if not hasattr(cloud_mod, "__path__"):
        cloud_mod.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google.cloud.aiplatform"] = types.ModuleType("google.cloud.aiplatform")


# Run immediately when conftest is loaded (before collection)
_install_google_adk_stubs()
