"""FastAPI Application Entrypoint for ChainRadar Engine"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import analytics, candidates, digests, evidence, review, sources
from src.config import settings
from src.scheduler.cadence import cadence_scheduler
from src.storage.database import db_manager

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chainradar.engine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup. The schema is owned by Alembic, not by the application:
    # calling create_all() here would silently diverge a running instance from
    # the migration history and mask a missed `alembic upgrade`.
    await db_manager.verify_schema_is_current()
    
    logger.info("Starting CadenceScheduler...")
    await cadence_scheduler.start()
    
    yield
    
    # Shutdown
    logger.info("Shutting down CadenceScheduler and database connections...")
    await cadence_scheduler.shutdown()
    await db_manager.close()


app = FastAPI(
    title="ChainRadar Early Chain Discovery & Africa Expansion Intelligence Engine",
    description="Production-ready, evidence-first intelligence engine discovering public blockchains before or shortly after mainnet.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Wildcard origins combined with credentials is rejected by browsers and
    # would expose an internal analyst tool to any site. Configure the real
    # origins for a deployment via CORS_ALLOWED_ORIGINS.
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# API Routers
app.include_router(candidates.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(digests.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(review.router, prefix="/api")


# UI Directory Setup
UI_DIR = Path(__file__).resolve().parent / "ui"

if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>ChainRadar Early Chain Discovery Engine API Running</h2><p>Visit <a href='/docs'>/docs</a> for API specifications.</p>")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "early-chain-discovery-africa-engine",
        "version": "1.0.0",
        "timezone_display": settings.TIMEZONE_DISPLAY,
        "storage_timezone": settings.STORAGE_TIMEZONE,
    }
