import uuid
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from ingest.services.report_service import ReportService
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from db_setup import Run, User, Result, Rule
from sqlmodel import Session, select
import logging
from pathlib import Path

# Assuming you have a get_session dependency in database.py
from database import get_session
from ingest.services.auth_service import require_user
from ingest.services.case_access import authorize_run

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/report", tags=["Report"])

# Note: ReportService instance is created once, outside the functions
report_service = ReportService()


@router.post("/generate")
async def generate_report(
    run_id: str,
    session: Session = Depends(get_session),
    auth_user: User = Depends(require_user),
):
    """
    Generate a PDF report for a given run_id.
    Pulls results from DB and formats them.

    Case-level RBAC: caller must hold 'viewer' on the run. Authorization runs
    BEFORE the broad try/except below so a 401/403/404 is never masked as a 500.
    """
    # Parse + authorize up front. authorize_run resolves existence (404) and
    # membership (403); its HTTPException must escape the catch-all below.
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid run_id format: {run_id}")
    authorize_run(session, auth_user, run_uuid)

    try:
        # Fetch run using the injected session
        run = session.exec(select(Run).where(Run.id == run_uuid)).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Fetch related user
        user = session.get(User, run.user_id)

        # Fetch results
        results = session.exec(select(Result).where(Result.run_id == run.id)).all()

        # Fetch rules for results
        rules_map = {
            r.id: r
            for r in session.exec(
                select(Rule).where(Rule.id.in_([res.rule_id for res in results]))
            ).all()
        }

        # Normalize for ReportService
        report_data = {
            "run_id": str(run.id),
            "ufdr_file_name": run.ufdr_file_name,
            "status": run.status,
            "start_time": str(run.start_time),
            "end_time": str(run.end_time) if run.end_time else None,
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
            },
            "results": [
                {
                    "id": str(res.id),
                    "rule": rules_map[res.rule_id].title
                    if res.rule_id in rules_map
                    else None,
                    "result_type": res.result_type,
                    "evidence_data": res.evidence_data,
                    "confidence_score": res.confidence_score,
                    "created_at": str(res.created_at),
                }
                for res in results
            ],
        }

        # Generate PDF
        pdf_path = report_service.generate_pdf(report_data)

        return {"status": "success", "pdf_path": pdf_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
async def download_report(
    filename: str,
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth_user: User = Depends(require_user),
):
    """
    Download a previously generated PDF report.
    """
    authorize_run(session, auth_user, run_id)
    if Path(filename).name != filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid report filename")
    if not filename.startswith(f"{run_id}_"):
        raise HTTPException(
            status_code=403,
            detail="report filename is not bound to the authorized case",
        )
    file_path = report_service.output_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(file_path), media_type="application/pdf")
