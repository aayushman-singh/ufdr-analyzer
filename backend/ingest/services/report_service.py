from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from typing import Dict, Any
from pathlib import Path
import uuid
import logging
from collections import Counter
import json

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ReportService:
    """
    Generates PDF reports from DB-backed run data.
    """

    def __init__(self, output_dir: str = "storage/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"ReportService initialized, output folder: {self.output_dir}"
        )

    def generate_pdf(self, data: Dict[str, Any]) -> str:
        report_id = str(uuid.uuid4())
        file_path = self.output_dir / f"{report_id}.pdf"

        c = canvas.Canvas(str(file_path), pagesize=A4)
        width, height = A4

        # === Title ===
        c.setFont("Helvetica-Bold", 16)
        c.drawString(
            50,
            height - 50,
            f"UFDR Report - Run ID: {data.get('run_id')}")

        # === Run Details ===
        c.setFont("Helvetica", 12)
        y = height - 100
        c.drawString(50, y, f"UFDR File: {data.get('ufdr_file_name', 'N/A')}")
        y -= 20
        c.drawString(50, y, f"Status: {data.get('status', 'N/A')}")
        y -= 20
        c.drawString(50, y, f"Start Time: {data.get('start_time', 'N/A')}")
        y -= 20
        c.drawString(50, y, f"End Time: {data.get('end_time', 'N/A')}")
        y -= 40

        # === User Info ===
        user = data.get("user", {})
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "Investigating Officer:")
        y -= 20
        c.setFont("Helvetica", 12)
        c.drawString(60, y, f"Name: {user.get('username', 'N/A')}")
        y -= 20
        c.drawString(60, y, f"Email: {user.get('email', 'N/A')}")
        y -= 40

        # === Results Summary ===
        results = data.get("results", [])
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "Results Summary:")
        y -= 20
        c.setFont("Helvetica", 12)

        type_counts = Counter(res["result_type"] for res in results)
        for rtype, count in type_counts.items():
            c.drawString(60, y, f"{rtype}: {count}")
            y -= 20

        y -= 20

        # === Sample Results (first 5 only) ===
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "Sample Results:")
        y -= 20
        c.setFont("Helvetica", 11)

        for res in results[:5]:
            c.drawString(60, y, f"- Rule: {res.get('rule', 'N/A')}")
            y -= 15
            c.drawString(
                80,
                y, f"Type: {res.get('result_type')}, "
                f"Score: {res.get('confidence_score')}")
            y -= 15
            try:
                evidence = json.loads(res.get("evidence_data", "{}"))
                snippet = (
                    str(evidence)[:80] + "..."
                    if len(str(evidence)) > 80
                    else str(evidence)
                )
                c.drawString(80, y, f"Evidence: {snippet}")
            except Exception:
                c.drawString(80, y, "Evidence: [Invalid JSON]")
            y -= 25
            if y < 100:  # New page if too low
                c.showPage()
                y = height - 100

        c.showPage()
        c.save()

        logger.info(f"Generated PDF report at {file_path}")
        return str(file_path)
