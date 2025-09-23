# backend/main.py
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlmodel import Session
from meilisearch import Client as MeiliClient
import os

from ingest.routers import health, upload, report
from database import create_db_and_tables, get_session
from ingest.services.ingest_service import IngestService
from ingest.utils.logger import get_logger
from config import APP_NAME, APP_VERSION

logger = get_logger(__name__)

# Meilisearch client
MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
MEILI_KEY = os.getenv("MEILI_KEY", None)
meili_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events for the application.
    - On startup, it connects to Meilisearch and creates DB tables.
    - On shutdown, it gracefully closes the Meilisearch connection.
    """
    global meili_client
    logger.info("Application starting up...")

    try:
        # Connect to Meilisearch
        meili_client = MeiliClient(MEILI_URL, MEILI_KEY)
        logger.info(f"Connected to Meilisearch at {MEILI_URL}")

        # Create DB and tables on startup
        create_db_and_tables()
        logger.info("Database and tables initialized.")
    except Exception as e:
        logger.error(f"Failed to connect to required services on startup: {e}")

    yield

    # On shutdown
    logger.info("Application shutting down...")
    if meili_client:
        # Meilisearch client doesn't need explicit closing
        logger.info("Meilisearch client closed.")

app = FastAPI(
    lifespan=lifespan,
    title=APP_NAME,
    version=APP_VERSION,
    description="Backend for AI-based UFDR Analysis Tool"
)

# ------------------------
# Dependency Injection
# ------------------------


def get_ingest_service(session: Session = Depends(get_session)):
    """Provides an instance of IngestService with a DB session."""
    return IngestService()


def get_meili_client():
    """Provides the Meilisearch client instance."""
    return meili_client

# ------------------------
# CORS settings
# ------------------------


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# Include Routers
# ------------------------
app.include_router(health.router)
app.include_router(upload.router)
app.include_router(report.router)

# ------------------------
# Root endpoint
# ------------------------


@app.get("/")
async def root():
    return {"message": f"{APP_NAME} is running!"}
