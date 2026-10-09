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
from ai.query_pipeline import _cite_row  # noqa: E402
from ai.query_plan import FieldName, Op, Predicate, QueryPlan, Target  # noqa: E402


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


def _contains_plan(target, field, value):
    return QueryPlan(
        targets=[target],
        predicates=[Predicate(field=field, op=Op.contains, values=[value])],
    )


def test_citation_preserves_source_casing_and_full_source_coordinates():
    source = "A WhatsApp message confirms the Bank Transfer was received."
    plan = _contains_plan(Target.messages, FieldName.text, "bank transfer")

    citation = _cite_row(
        Target.messages, {"row_id": "message-1", "content": source}, plan
    )[0]

    assert citation.matched_value == "Bank Transfer"
    assert citation.snippet == source
    assert source[citation.char_start : citation.char_end] == "Bank Transfer"
    assert 0 <= citation.char_start < citation.char_end <= len(source)


def test_citation_does_not_truncate_long_source_text():
    source = "prefix " + ("context " * 12) + "Bank Transfer" + (" detail" * 12)
    plan = _contains_plan(Target.messages, FieldName.text, "bank transfer")

    citation = _cite_row(
        Target.messages, {"row_id": "message-2", "content": source}, plan
    )[0]

    assert citation.snippet == source
    assert "..." not in citation.snippet
    assert source[citation.char_start : citation.char_end] == citation.matched_value


def test_repeated_text_uses_first_deterministic_source_span():
    source = "Bank transfer noted; later bank transfer reversed."
    plan = _contains_plan(Target.messages, FieldName.text, "bank transfer")

    citation = _cite_row(
        Target.messages, {"row_id": "message-3", "content": source}, plan
    )[0]

    assert citation.char_start == 0
    assert citation.matched_value == "Bank transfer"
    assert source[citation.char_start : citation.char_end] == citation.matched_value


def test_missing_predicate_fails_closed():
    plan = _contains_plan(Target.messages, FieldName.text, "bank transfer")

    with pytest.raises(ValueError, match="citation predicate"):
        _cite_row(Target.messages, {"row_id": "message-4", "content": "No match"}, plan)


def test_non_text_source_value_fails_closed():
    plan = _contains_plan(Target.messages, FieldName.text, "123")

    with pytest.raises(ValueError, match="source value"):
        _cite_row(Target.messages, {"row_id": "message-5", "content": 123}, plan)


@pytest.mark.parametrize(
    ("field", "value", "expected_column"),
    [
        (FieldName.text, "WhatsApp", "filename"),
        (FieldName.app, "/evidence/WhatsApp/messages.csv", "file_path"),
        (FieldName.category, "Messages", "category"),
        (FieldName.text, "bank transfer", "data"),
    ],
)
def test_artifact_citations_use_canonical_supported_columns(
    field, value, expected_column
):
    row = {
        "row_id": "artifact-1",
        "data": '{"text": "bank transfer"}',
        "filename": "WhatsApp messages.csv",
        "file_path": "/evidence/WhatsApp/messages.csv",
        "category": "Messages",
    }
    plan = _contains_plan(Target.aleapp_artifacts, field, value)

    citations = _cite_row(Target.aleapp_artifacts, row, plan)

    assert any(c.column == expected_column for c in citations)
    for citation in citations:
        assert citation.snippet == row[citation.column]
        assert (
            row[citation.column][citation.char_start : citation.char_end]
            == citation.matched_value
        )
