import pytest
from pathlib import Path
import shutil

REPORT_DIR = Path("storage/reports")


@pytest.fixture(autouse=True)
def clean_reports_dir():
    """Ensure reports directory is clean before and after tests."""
    if REPORT_DIR.exists():
        shutil.rmtree(REPORT_DIR)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(REPORT_DIR)


def test_generate_report_with_valid_run_id(client):
    """
    Simulate a run and then generate a report for it.
    This test will fail until a proper test database is set up with a
      valid run_id.
    """
    dummy_run_id = "1b2a2e4e-0a5d-4f7f-8c7c-4a3b1f5e8d9c"

    response = client.post(f"/report/generate?run_id={dummy_run_id}")

    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data["status"] == "success"
    assert "pdf_path" in resp_data

    pdf_path = Path(resp_data["pdf_path"])
    assert pdf_path.exists()


def test_generate_report_run_not_found(client):
    """Test generating a report for a non-existent run_id."""
    invalid_run_id = "non-existent-id"
    response = client.post(f"/report/generate?run_id={invalid_run_id}")
    assert response.status_code == 404
    assert "Report not found" in response.json()["detail"]


def test_download_report_success(client):
    """Test downloading a manually created dummy PDF file."""
    dummy_pdf_path = REPORT_DIR / "test_report_download.pdf"
    with open(dummy_pdf_path, "w") as f:
        f.write("This is a dummy PDF file.")

    resp = client.get(f"/report/download/{dummy_pdf_path.name}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"


def test_download_report_not_found(client):
    """Test that a 404 is returned for a non-existent file."""
    resp = client.get("/report/download/nonexistent.pdf")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Report not found"
