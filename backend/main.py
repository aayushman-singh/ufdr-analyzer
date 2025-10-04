# backend/main.py
from fastapi import FastAPI, Depends, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlmodel import Session
from meilisearch import Client as MeiliClient
import os
import time
import json

from ingest.routers import health, upload, report, query
from database import create_db_and_tables, get_session
from ingest.services.ingest_service import IngestService
from ingest.utils.logger import get_logger
from config import APP_NAME, APP_VERSION
import subprocess
import os

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

# Configure for large file uploads
app.router.mount_lifespan = False

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
# Request Logging Middleware
# ------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests and responses for debugging."""
    start_time = time.time()
    
    # Log request details
    logger.info(f"Request: {request.method} {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Query params: {dict(request.query_params)}")
    
    # Log request body for POST/PUT requests (but be careful with large files)
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            # Only log body for non-file uploads to avoid memory issues
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" not in content_type:
                body = await request.body()
                if body:
                    try:
                        body_str = body.decode("utf-8")
                        logger.info(f"Request body: {body_str[:1000]}...")  # Limit to first 1000 chars
                    except UnicodeDecodeError:
                        logger.info(f"Request body: <binary data, {len(body)} bytes>")
                else:
                    logger.info("Request body: <empty>")
        except Exception as e:
            logger.warning(f"Could not read request body: {e}")
    
    # Process request
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Log response details
        logger.info(f"Response: {response.status_code} (took {process_time:.3f}s)")
        logger.info(f"Response headers: {dict(response.headers)}")
        
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed after {process_time:.3f}s: {e}")
        raise

# ------------------------
# Exception Handlers
# ------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with detailed logging."""
    logger.error(f"Request validation error: {exc}")
    logger.error(f"Request URL: {request.url}")
    logger.error(f"Request method: {request.method}")
    logger.error(f"Request headers: {dict(request.headers)}")
    
    # Log the specific validation errors
    for error in exc.errors():
        logger.error(f"Validation error: {error}")
    
    return JSONResponse(
        status_code=400,
        content={
            "detail": "There was an error parsing the body",
            "errors": exc.errors(),
            "request_info": {
                "url": str(request.url),
                "method": request.method,
                "content_type": request.headers.get("content-type", "unknown")
            }
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with logging."""
    logger.error(f"HTTP exception: {exc.status_code} - {exc.detail}")
    logger.error(f"Request URL: {request.url}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

# ------------------------
# Include Routers
# ------------------------
app.include_router(health.router)
app.include_router(upload.router)
app.include_router(report.router)
app.include_router(query.router)

# ------------------------
# Root endpoint
# ------------------------


@app.get("/")
async def root():
    return {"message": f"{APP_NAME} is running!"}

# ------------------------
# ALEAPP Integration
# ------------------------

def run_aleapp_analysis(input_path: str, output_path: str) -> dict:
    """
    Run ALEAPP analysis with admin privileges
    
    Args:
        input_path: Path to Android extraction directory
        output_path: Path where ALEAPP report should be saved
    
    Returns:
        dict: Result of the ALEAPP analysis
    """
    try:
        # Get the path to our admin wrapper script
        script_path = os.path.join(os.path.dirname(__file__), 'run_aleapp_admin.py')
        
        # Run the admin wrapper script
        result = subprocess.run([
            'python', script_path, input_path, output_path
        ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "ALEAPP analysis timed out after 1 hour",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "returncode": -1
        }
