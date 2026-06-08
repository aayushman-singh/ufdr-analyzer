"""Voice-note transcription endpoints."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from database import get_session
from db_setup import Transcript
from ingest.services.audit_service import audit_service
from ingest.services.transcription_service import TranscriptionService

router = APIRouter(prefix="/transcription", tags=["Voice-note Transcription"])


@router.post("/run")
def transcribe_run(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """Transcribe every audio item in a run; persist + audit each transcript.

    Uses the default faster-whisper transcriber, which fails loudly if the model
    package is not installed (audio is never silently skipped)."""
    try:
        results = TranscriptionService().transcribe_run(session, run_id, audit_service=audit_service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"run_id": str(run_id), "transcribed": len(results),
            "transcripts": [r.to_dict() for r in results]}


@router.get("/run")
def list_transcripts(run_id: uuid.UUID = Query(...), session: Session = Depends(get_session)) -> dict:
    """List stored transcripts for a run."""
    rows = session.exec(select(Transcript).where(Transcript.run_id == run_id)).all()
    return {
        "run_id": str(run_id),
        "count": len(rows),
        "transcripts": [
            {"transcript_id": str(t.id), "media_id": str(t.media_id), "model": t.model,
             "language": t.language, "text": t.text, "transcript_hash": t.transcript_hash}
            for t in rows
        ],
    }
