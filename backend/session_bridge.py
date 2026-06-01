"""SessionBridge — Injects voice transcripts into the text orchestrator's ADK session.

When the user talks via voice mode, the ``audio_agent`` accumulates its own
event history inside the shared ``InMemorySessionService``.  The text
``rs_agent`` (orchestrator) however has a **separate** event list and never
sees what was said in voice mode.

This class bridges the gap: after every completed voice turn it creates
synthetic ``Content`` events (user + model) and appends them to the
orchestrator's session via ``session_service.append_event()``.  This way
the orchestrator has full conversational context when the user switches
back to text chat.

Design decisions
----------------
* **Content events, NOT transcription events** — ``_extract_conversation_text()``
  reads ``event.content.parts[].text`` and ignores transcription fields.
  Injecting ``Content`` events makes voice turns visible to that helper.
* **No Firestore writes** — persistence is already handled by
  ``downstream_task()`` calling ``append_conversation_turn()``.
* **No WebSocket messages** — chat bubbles are already sent by the WS handler.
* **Lazy session creation** — if the orchestrator session doesn't exist yet
  (e.g. user started directly in voice mode), one is created on the fly.
* **Idempotency guard** — empty transcripts are silently skipped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from google.adk.events.event import Event
from google.genai import types

if TYPE_CHECKING:
    from google.adk.sessions import InMemorySessionService

logger = logging.getLogger(__name__)


class SessionBridge:
    """Bridges voice transcripts into the text orchestrator's ADK session.

    Parameters
    ----------
    session_service:
        The shared ``InMemorySessionService`` used by both runners.
    app_name:
        ADK application name (must match the runner's ``app_name``).
    orchestrator_agent_name:
        The ``name`` attribute of the text orchestrator agent.  Used as
        the ``author`` field on injected model events so that
        ``_extract_conversation_text()`` can map them to "Consultant".
    """

    def __init__(
        self,
        session_service: InMemorySessionService,
        app_name: str,
        orchestrator_agent_name: str = "business_analyst_orchestrator",
    ) -> None:
        self._session_service = session_service
        self._app_name = app_name
        self._orchestrator_agent_name = orchestrator_agent_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def inject_voice_turn(
        self,
        user_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Inject a completed voice turn into the orchestrator's ADK session.

        Creates two synthetic ``Event`` objects (one ``user``, one ``model``)
        wrapping plain ``Content`` and appends them via the session service.

        Parameters
        ----------
        user_id:
            The user who owns the session.
        session_id:
            Session identifier (same for voice and text — they share one
            logical conversation).
        user_text:
            Final user transcription from the voice turn.
        assistant_text:
            Final assistant transcription from the voice turn.
        """
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()

        if not user_text and not assistant_text:
            logger.debug(f"[SessionBridge] Skipping injection — both transcripts empty: session={session_id}")
            return

        session = await self._get_or_create_session(user_id, session_id)

        content_events = [e for e in (session.events or []) if e.content and e.content.parts]
        logger.info(
            f"[SessionBridge] Session state before injection: "
            f"session={session_id} total_events={len(session.events or [])} "
            f"content_events={len(content_events)}"
        )

        # --- Inject user event ---
        if user_text:
            user_event = self._make_user_event(user_text)
            await self._session_service.append_event(session, user_event)
            logger.debug(f"[SessionBridge] Injected user event ({len(user_text)} chars): session={session_id}")

        # --- Inject model (assistant) event ---
        if assistant_text:
            model_event = self._make_model_event(assistant_text)
            await self._session_service.append_event(session, model_event)
            logger.debug(f"[SessionBridge] Injected model event ({len(assistant_text)} chars): session={session_id}")

        logger.info(
            f"[SessionBridge] Voice turn injected into orchestrator session: "
            f"session={session_id} user_chars={len(user_text)} "
            f"assistant_chars={len(assistant_text)}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_or_create_session(self, user_id: str, session_id: str):
        """Return the orchestrator's ADK session, creating it if needed.

        This handles the case where the user starts with voice mode before
        ever sending a text message — the orchestrator session wouldn't
        exist yet.
        """
        session = await self._session_service.get_session(
            app_name=self._app_name,
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            session = await self._session_service.create_session(
                app_name=self._app_name,
                user_id=user_id,
                session_id=session_id,
            )
            logger.info(f"[SessionBridge] Created orchestrator session on demand: session={session_id}")
        return session

    def _make_user_event(self, text: str) -> Event:
        """Create a synthetic user ``Event`` wrapping a plain text ``Content``."""
        return Event(
            author="user",
            content=types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            ),
        )

    def _make_model_event(self, text: str) -> Event:
        """Create a synthetic model ``Event`` wrapping a plain text ``Content``.

        Uses the orchestrator agent's name as ``author`` so the event looks
        like it came from the text agent (consistent with how the runner
        records model responses).
        """
        return Event(
            author=self._orchestrator_agent_name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=text)],
            ),
        )
