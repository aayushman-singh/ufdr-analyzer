import os
import sys
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

if "meilisearch" not in sys.modules:
    meili = types.ModuleType("meilisearch")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

    meili.Client = FakeClient
    sys.modules["meilisearch"] = meili

if "ai.embeddings" not in sys.modules:
    embeddings = types.ModuleType("ai.embeddings")

    class FakeEmbeddingsService:
        pass

    embeddings.EmbeddingsService = FakeEmbeddingsService
    sys.modules["ai.embeddings"] = embeddings

from ai.query_executor import QueryExecutor  # noqa: E402


def test_invalid_search_type_fails_loud():
    executor = QueryExecutor(session=object(), meili_client=object())

    with pytest.raises(ValueError, match="unsupported search_type"):
        executor.execute(
            "00000000-0000-0000-0000-000000000001",
            {"target_tables": ["messages"], "search_type": "mystery"},
        )


def test_unknown_target_table_fails_loud():
    executor = QueryExecutor(session=object(), meili_client=object())

    with pytest.raises(ValueError, match="unsupported target_tables"):
        executor.execute(
            "00000000-0000-0000-0000-000000000001",
            {"target_tables": ["secrets"], "search_type": "keyword"},
        )
