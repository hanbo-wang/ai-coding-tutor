"""FastAPI application entry point with startup initialisation and logging."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.db.session import engine
from app.db.init_db import init_db
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.health import (
    ai_model_catalog_health_check,
    render_health_page_html,
    router as health_router,
)
from app.routers.upload import router as upload_router
from app.routers.notebooks import router as notebooks_router
from app.routers.zones import router as zones_router
from app.routers.admin import router as admin_router


def _configure_logging() -> None:
    """Set up structured logging for the application."""
    root_logger = logging.getLogger("ai_tutor")
    root_logger.setLevel(logging.INFO)

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Propagate ai_tutor.* loggers to the root handler.
    for name in ("app.routers.chat", "app.routers.admin", "app.ai", "app.services"):
        logging.getLogger(name).setLevel(logging.INFO)


_configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="AI Coding Tutor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(notebooks_router)
app.include_router(zones_router)
app.include_router(admin_router)


@app.get("/health")
async def health_check(request: Request, force: bool = False):
    """Health check endpoint (JSON for probes, HTML page for browsers)."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        model_health = await ai_model_catalog_health_check(force=force)
        return HTMLResponse(render_health_page_html(model_health))
    return {"status": "healthy"}
