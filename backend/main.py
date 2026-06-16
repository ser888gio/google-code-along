from __future__ import annotations

import os

from api import chat, diagrams, discovery, documents, feedback, sessions
from config import validate_config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from logger import get_logger, setup_logging
from observability.tracing import setup_telemetry
from starlette.requests import Request

setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="RS Generator API")

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)

setup_telemetry(app)


@app.on_event("startup")
async def validate_runtime_config() -> None:
    """Fail fast with explicit config errors before serving traffic."""
    for warning in validate_config():
        logger.warning(warning)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return a JSON 500 for any unhandled exception.

    This ensures the response flows through CORSMiddleware so the browser
    always receives Access-Control-Allow-Origin headers — even on errors.
    """
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(chat.router)
app.include_router(diagrams.router)
app.include_router(discovery.router)
app.include_router(documents.router)
app.include_router(feedback.router)
app.include_router(sessions.router)
