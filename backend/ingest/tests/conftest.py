from io import BytesIO

import pytest


@pytest.fixture
def client():
    """
    Returns a TestClient instance for FastAPI app.

    `main` pulls in the full app (meilisearch, routers, etc.). Importing it
    lazily here keeps test *collection* from erroring when those heavy deps
    are not installed; the test modules using this fixture skip-guard them.
    """
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


@pytest.fixture
def dummy_ufdr_file():
    """
    Returns a dummy UFDR file-like object for upload tests.
    """
    file_content = b'{"dummy": "data"}'
    file_obj = BytesIO(file_content)
    file_obj.name = "dummy.ufdr.json"
    return file_obj


@pytest.fixture
def dummy_ufdr_json():
    """
    Returns a dummy UFDR JSON structure for report tests.
    """
    return {
        "filename": "dummy.ufdr",
        "messages": [{"from": "Alice", "to": "Bob", "text": "Hello"}],
        "contacts": [{"name": "Alice", "number": "12345"}],
        "calls": [],
        "media": []
    }
