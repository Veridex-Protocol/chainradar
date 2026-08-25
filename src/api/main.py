"""FastAPI Application Entrypoint for Ashinity Early Chain Discovery & Africa Intelligence Engine."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import analytics, candidates, digests, evidence, sources
from src.config import settings
from src.scheduler.cadence import cadence_scheduler
from src.storage.database import db_manager

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ashinity.engine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Ashinity Intelligence Engine database & tables...")
    await db_manager.init_db()
    
    logger.info("Starting CadenceScheduler...")
    await cadence_scheduler.start()
    
    yield
    
    # Shutdown
    logger.info("Shutting down CadenceScheduler and database connections...")
    await cadence_scheduler.shutdown()
    await db_manager.close()


app = FastAPI(
    title="Ashinity Early Chain Discovery & Africa Expansion Intelligence Engine",
    description="Production-ready, evidence-first intelligence engine discovering public blockchains before or shortly after mainnet.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(candidates.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(digests.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")


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
    return HTMLResponse("<h2>Ashinity Early Chain Discovery Engine API Running</h2><p>Visit <a href='/docs'>/docs</a> for API specifications.</p>")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "early-chain-discovery-africa-engine",
        "version": "1.0.0",
        "timezone_display": settings.TIMEZONE_DISPLAY,
        "storage_timezone": settings.STORAGE_TIMEZONE,
    }
