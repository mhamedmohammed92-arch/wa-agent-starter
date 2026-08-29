"""Application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .config import settings
from .faq import FaqBook
from .webhook import router as webhook_router


def _setup_logging() -> None:
    """Attach a handler to our own logger names.

    basicConfig on the root logger is not enough: uvicorn applies its own
    dictConfig per worker and resets the root logger, which silently throws away
    every line this app writes.
    """
    level = (os.getenv("LOG_LEVEL") or settings.LOG_LEVEL or "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger = logging.getLogger("wa_agent")
    logger.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False


_setup_logging()
log = logging.getLogger("wa_agent.main")


def load_faq() -> FaqBook:
    """Load the answer book, resolving a relative FAQ_FILE against the project
    root so the app starts the same way from any working directory."""
    path = Path(settings.FAQ_FILE)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    book = FaqBook.load(path, settings.DEFAULT_LANGUAGE)
    log.info("loaded %d intents from %s", len(book.intents), path)
    return book


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.faq = load_faq()
    if not settings.send_configured:
        log.warning(
            "WhatsApp credentials are not set - replies will be logged, not sent"
        )
    if settings.ALLOW_UNSIGNED_WEBHOOK:
        log.warning(
            "ALLOW_UNSIGNED_WEBHOOK is enabled - acceptable on localhost only"
        )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Minimal WhatsApp agent on the Meta Cloud API (MIT).",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict:
    """Liveness probe, and a quick read on how the instance is configured.
    It deliberately reports only booleans - never a secret, not even masked."""
    return {
        "status": "ok",
        "intents": len(getattr(app.state, "faq", None).intents)
        if getattr(app.state, "faq", None)
        else 0,
        "sending_enabled": settings.send_configured,
        "signature_enforced": not settings.ALLOW_UNSIGNED_WEBHOOK,
        "app_secret_set": bool(settings.META_APP_SECRET.strip()),
        "verify_token_set": bool(settings.WHATSAPP_VERIFY_TOKEN.strip()),
    }
