"""Structured logging via google-cloud-logging.

On Cloud Run, `setup_logging()` installs the Cloud Logging handler so every
`logging.*` call is emitted as a structured JSON entry linked to the active
Cloud Trace span (X-Cloud-Trace-Context is populated automatically by the
platform).

Outside GCP (local dev / CI), if the Cloud Logging client cannot authenticate,
we fall back to a plain stdout handler so the app still runs.
"""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger. Call once at application startup."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Prefer Cloud Logging when running on GCP (K_SERVICE is set on Cloud Run)
    # or when credentials are explicitly available.
    if os.getenv("K_SERVICE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            import google.cloud.logging as cloud_logging

            client = cloud_logging.Client()
            # setup_logging installs a handler on the root logger that emits
            # structured JSON and auto-correlates to Cloud Trace spans.
            client.setup_logging(log_level=log_level)
            return
        except Exception:
            # Fall through to stdout handler if anything goes wrong
            pass

    # Local dev fallback — plain stdout
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Pass __name__ from the calling module."""
    return logging.getLogger(name)
