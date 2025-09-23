# backend/utils/pdf_utils.py
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)


def create_pdf_canvas(output_path: str, pagesize=A4) -> canvas.Canvas:
    """
    Creates and returns a reportlab Canvas object.
    Ensures the output folder exists.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=pagesize)
    logger.info(f"PDF canvas created at {output_path}")
    return c


def save_canvas(c: canvas.Canvas):
    """
    Saves the canvas to the file.
    """
    c.showPage()
    c.save()
    logger.info("PDF saved successfully")


def add_title(c: canvas.Canvas, title: str, x=50, y=800, font_size=16):
    """
    Adds a title to the PDF canvas.
    """
    c.setFont("Helvetica-Bold", font_size)
    c.drawString(x, y, title)


def add_text(c: canvas.Canvas, text: str, x=50, y=780, font_size=12):
    """
    Adds regular text to the PDF canvas.
    """
    c.setFont("Helvetica", font_size)
    c.drawString(x, y, text)
