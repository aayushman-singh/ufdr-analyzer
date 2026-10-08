import json
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from config import APP_NAME, APP_VERSION, CORS_ALLOWED_ORIGINS, DEMO_MODE
from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from meilisearch import Client as MeiliClient
from sqlmodel import Session, select
from dotenv import load_dotenv

from database import create_db_and_tables, get_session
from db_setup import (
    AleappArtifact,
    AleappReport,
    Call,
    CaseMembership,
    Contact,
    EntityIndex,
    Media,
    Message,
    Query,
    Result,
    Run,
    Transcript,
    User,
)
from ingest.routers import (
    aleapp_structure,
    analytics_router,
    audit_router,
    auth_router,
    case_access_router,
    cross_case_router,
    entity_router,
    health,
    link_graph_router,
    query,
    query_plan_router,
    report,
    sync_router,
    transcription_router,
    upload,
)
from ingest.services.ingest_service import IngestService
from ingest.services.auth_service import require_user
from ingest.utils.logger import get_logger

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = get_logger(__name__)
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}
CANONICAL_DEMO_RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CANONICAL_DEMO_FILE_NAME = "demo_synthetic.ufdr"
CANONICAL_DEMO_OWNER_EMAIL = "citespan-demo-owner@example.invalid"
CANONICAL_DEMO_MARKER = "citespan-synthetic-demo-v1"
CANONICAL_DEMO_MESSAGES = (
    (
        "+15551234567",
        "+15559876543",
        "Can you send the bitcoin wallet address for the transfer?",
    ),
    (
        "+15559876543",
        "+15551234567",
        "Use the bank transfer reference for the synthetic sample.",
    ),
)
CANONICAL_DEMO_ARTIFACT = {
    "artifact_type": "csv",
    "filename": "whatsapp_messages.csv",
    "file_path": "/synthetic/whatsapp_messages.csv",
    "category": "WhatsApp messages",
    "row_count": 1,
    "data": json.dumps(
        {
            "message": "The synthetic WhatsApp message confirms the bank transfer reference."
        },
        sort_keys=True,
    ),
}


def _validate_canonical_demo_run(session: Session, run: Run) -> User:
    """Reject every configured run that is not the exact synthetic sample."""
    if run.id != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError("configured demo run identity is not canonical")
    if run.ufdr_file_name != CANONICAL_DEMO_FILE_NAME:
        raise RuntimeError("configured demo run filename is not canonical")
    owner = session.get(User, run.user_id)
    if owner is None or owner.email != CANONICAL_DEMO_OWNER_EMAIL:
        raise RuntimeError("configured demo run owner is not the canonical demo owner")
    try:
        metadata = json.loads(run.extraction_metadata or "")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("configured demo run synthetic marker is invalid") from exc
    if metadata != {
        "citespan_marker": CANONICAL_DEMO_MARKER,
        "owner_email": CANONICAL_DEMO_OWNER_EMAIL,
        "sample_id": "canonical-v1",
        "synthetic_only": True,
    }:
        raise RuntimeError(
            "configured demo run synthetic marker or ownership is invalid"
        )

    messages = session.exec(select(Message).where(Message.run_id == run.id)).all()
    observed_messages = tuple(
        (item.sender, item.receiver, item.content)
        for item in sorted(messages, key=lambda item: item.timestamp)
    )
    if observed_messages != CANONICAL_DEMO_MESSAGES:
        raise RuntimeError(
            "configured demo run contains non-canonical message contents"
        )
    artifacts = session.exec(
        select(AleappArtifact).where(AleappArtifact.run_id == run.id)
    ).all()
    observed_artifacts = [
        {key: getattr(item, key) for key in CANONICAL_DEMO_ARTIFACT}
        for item in artifacts
    ]
    if observed_artifacts != [CANONICAL_DEMO_ARTIFACT]:
        raise RuntimeError("configured demo run contains non-canonical artifacts")
    for model in (
        AleappReport,
        Call,
        Contact,
        EntityIndex,
        Media,
        Query,
        Result,
        Transcript,
    ):
        if (
            session.exec(select(model).where(model.run_id == run.id)).first()
            is not None
        ):
            raise RuntimeError(
                f"configured demo run contains a forbidden {model.__name__} row"
            )
    return owner


def _redacted_headers(headers) -> dict:
    return {
        key: ("<redacted>" if key.lower() in _SENSITIVE_HEADERS else value)
        for key, value in headers.items()
    }


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
        # Create DB and tables on startup
        create_db_and_tables()
        logger.info("Database and tables initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    try:
        meili_client = MeiliClient(MEILI_URL, MEILI_KEY)
        logger.info(f"Connected to Meilisearch at {MEILI_URL}")
    except Exception as e:
        logger.exception("MeiliSearch startup failed", extra={"meili_url": MEILI_URL})
        raise RuntimeError(f"MeiliSearch startup failed: {e}") from e

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
    description="Backend for CiteSpan evidence analysis",
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
    if meili_client is None:
        raise RuntimeError("Meilisearch client is not initialized")
    return meili_client


# ------------------------
# CORS settings
# ------------------------


# Credentialed CORS requires an explicit origin allow-list — the wildcard
# "*" + allow_credentials=True combo is rejected by the Fetch spec and was a
# real bug here. Origins come from config (CORS_ALLOWED_ORIGINS env var).
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _demo_data_request_blocked(path: str) -> bool:
    normalized = path.rstrip("/")
    return (
        normalized == "/ingest"
        or path.startswith("/ingest/")
        or normalized == "/api/ingest"
        or path.startswith("/api/ingest/")
        or normalized == "/upload"
        or path.startswith("/upload/")
        or path.startswith("/api/upload/")
    )


@app.middleware("http")
async def enforce_demo_data_policy(request: Request, call_next):
    """Reject every hosted-demo file and path ingestion request."""
    if DEMO_MODE and _demo_data_request_blocked(request.url.path):
        logger.error(
            "Demo data policy rejected request",
            extra={"method": request.method, "path": request.url.path},
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": "File upload and path ingestion are disabled in demo mode."
            },
        )
    return await call_next(request)


# ------------------------
# Request Logging Middleware
# ------------------------


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests and responses for debugging."""
    start_time = time.time()

    # Log request details
    logger.info(f"Request: {request.method} {request.url}")
    logger.info(f"Headers: {_redacted_headers(request.headers)}")
    logger.info(f"Query param keys: {list(request.query_params.keys())}")

    # Log request body for POST/PUT requests (but be careful with large files)
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            # Only log body for non-file uploads to avoid memory issues
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" not in content_type:
                body = await request.body()
                if body:
                    logger.info(f"Request body: <{len(body)} bytes redacted>")
                else:
                    logger.info("Request body: <empty>")
            else:
                logger.info("Request body: <multipart form data>")
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
    logger.error(f"Request headers: {_redacted_headers(request.headers)}")

    # Log the specific validation errors
    for error in exc.errors():
        logger.error(f"Validation error: {error}")

    # Clean up errors to ensure JSON serialization
    clean_errors = []
    for error in exc.errors():
        clean_error = {
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
            "input": str(error.get("input", ""))
            if error.get("input") is not None
            else None,
        }
        clean_errors.append(clean_error)

    return JSONResponse(
        status_code=400,
        content={
            "detail": "There was an error parsing the body",
            "errors": clean_errors,
            "request_info": {
                "url": str(request.url),
                "method": request.method,
                "content_type": request.headers.get("content-type", "unknown"),
            },
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with logging."""
    logger.error(f"HTTP exception: {exc.status_code} - {exc.detail}")
    logger.error(f"Request URL: {request.url}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ------------------------
# Include Routers
# ------------------------
app.include_router(health.router)
app.include_router(
    auth_router.router
)  # signup/login -> bearer token for owner-scoped routes
app.include_router(
    case_access_router.router
)  # case-level RBAC: grant/list/revoke per-case roles
app.include_router(upload.router)
app.include_router(report.router)
app.include_router(query.router)
app.include_router(query_plan_router.router)  # auditable NL -> IR -> cited results
app.include_router(audit_router.router)  # tamper-evident audit trail + signed PDF
app.include_router(entity_router.router)  # Postgres-CTE entity graph (slim profile)
app.include_router(analytics_router.router)  # temporal patterns / anomaly detection
app.include_router(cross_case_router.router)  # cross-case entity linking
app.include_router(
    link_graph_router.router
)  # provenance-cited cross-case link graph + signed export
app.include_router(transcription_router.router)  # voice-note transcription
app.include_router(sync_router.router)
app.include_router(aleapp_structure.router)

# ------------------------
# CORS Preflight Handler
# ------------------------


@app.options("/{path:path}")
async def options_handler(path: str):
    return {"message": "OK"}


# ------------------------
# Root endpoint
# ------------------------


@app.get("/")
async def root():
    return {"message": f"{APP_NAME} is running!"}


@app.post("/demo/reset")
def reset_demo_sample(
    session: Session = Depends(get_session),
    _user=Depends(require_user),
):
    """Return only the configured canonical synthetic run for the demo UI."""
    if not DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo reset is not enabled.")
    raw_run_id = os.getenv("CITESPAN_DEMO_RUN_ID")
    if not raw_run_id:
        raise RuntimeError("CITESPAN_DEMO_RUN_ID is required for demo reset")
    try:
        run_id = uuid.UUID(raw_run_id)
    except ValueError as exc:
        raise RuntimeError("CITESPAN_DEMO_RUN_ID is not a valid UUID") from exc
    if run_id != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError(
            "CITESPAN_DEMO_RUN_ID is not the canonical synthetic identity"
        )
    run = session.exec(select(Run).where(Run.id == run_id)).first()
    if run is None:
        raise RuntimeError("configured canonical demo run does not exist")
    owner = _validate_canonical_demo_run(session, run)
    membership = session.exec(
        select(CaseMembership).where(
            CaseMembership.run_id == run_id,
            CaseMembership.user_id == _user.id,
        )
    ).first()
    if membership is None and run.user_id != _user.id:
        session.add(
            CaseMembership(
                run_id=run_id,
                user_id=_user.id,
                role="viewer",
                granted_by=owner.id,
            )
        )
        session.commit()
    logger.info(
        "Demo reset selected canonical synthetic run", extra={"run_id": str(run_id)}
    )
    return {"run_id": str(run_id), "sample": "canonical synthetic UFDR", "reset": True}


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
        script_path = os.path.join(os.path.dirname(__file__), "run_aleapp_admin.py")

        # Run the admin wrapper script
        result = subprocess.run(
            ["python", script_path, input_path, output_path],
            capture_output=True,
            text=True,
            timeout=3600,
        )  # 1 hour timeout

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "ALEAPP analysis timed out after 1 hour",
            "returncode": -1,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "returncode": -1}
