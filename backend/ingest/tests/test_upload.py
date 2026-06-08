from io import BytesIO

import pytest

# The `client` fixture imports `main`, which loads meilisearch at module level.
pytest.importorskip("meilisearch")


def test_upload_ufdr(client):
    dummy_file = BytesIO(b'{"dummy": "data"}')
    dummy_file.name = "test.ufdr.json"

    response = client.post(
        "/upload/",
        files={"file": ("test.ufdr.json", dummy_file, "application/json")}
    )

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "success"
    assert "ingest_result" in data
