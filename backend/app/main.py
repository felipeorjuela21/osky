import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from backend.app.api.routes import router
from backend.app.core.config import settings
from backend.app.core.db import engine, init_db, knowledge_chunks

logger = logging.getLogger("uvicorn.error")

def _load_knowledge_if_empty() -> None:
    """Fills the knowledge base on first start: from the saved snapshot of the site
    (fast, works on the free server whose disk is wiped on each deploy), or by
    reading celuweb.com when there is no snapshot."""
    with engine.connect() as conn:
        if conn.execute(select(func.count()).select_from(knowledge_chunks)).scalar_one():
            return
    from backend.scripts.ingest_website import SNAPSHOT_PATH, ingest, load_snapshot

    try:
        if SNAPSHOT_PATH.exists():
            logger.info("Knowledge base empty: loading %s (%d chunks)", SNAPSHOT_PATH, load_snapshot(engine))
        else:
            logger.warning("Knowledge base empty: reading %s in background", settings.website_url)
            ingest(engine)
    except Exception:
        logger.exception("Could not load the knowledge base; run: python -m backend.scripts.ingest_website")

def _preload_stt() -> None:
    if settings.effective_stt != "whisper":
        return
    from backend.app.services.stt import get_model

    try:
        get_model()  # load Whisper now so the first spoken turn isn't slow
    except Exception:
        logger.exception("Could not load the Whisper model")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(engine, seed=settings.enable_demo_data)
    logger.info(
        "Osky providers: stt=%s tts=%s llm=%s (env=%s)",
        settings.effective_stt, settings.effective_tts, settings.effective_llm, settings.app_env,
    )
    threading.Thread(target=_load_knowledge_if_empty, daemon=True).start()
    threading.Thread(target=_preload_stt, daemon=True).start()
    yield

app = FastAPI(
    title=f"{settings.agent_name} - Enterprise Voice Data Agent",
    version="0.4.0",
    description=f"{settings.company_name} voice agent. Company sources are the source of truth.",
    lifespan=lifespan,
    # No public API explorer in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/health")
def health():
    from backend.app.services.stt import is_ready

    return {
        "status": "ok",
        "service": "enterprise-voice-data-agent",
        "agent": settings.agent_name,
        "stt_ready": is_ready(),
    }
