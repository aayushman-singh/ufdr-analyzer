"""Smoke test over ALREADY-EXTRACTED UFDR artifacts.

This never touches the source ``*.ufdr`` archive nor re-runs extraction. It only
inspects the directory the Rust/Python extractor leaves behind under
``backend/UFDRConvert/<case>/``. That tree is large and may be gitignored /
local-only, so when it is absent the test skips loudly at runtime rather than
silently passing.
"""
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
EXTRACTED = BACKEND / "UFDRConvert" / "test_comprehensive"


@pytest.fixture(scope="module")
def extracted_dir() -> Path:
    if not EXTRACTED.is_dir():
        pytest.skip(f"extracted artifacts not present at {EXTRACTED}")
    return EXTRACTED


def test_extraction_directory_is_populated(extracted_dir: Path):
    """The extractor left at least one file behind."""
    entries = [p for p in extracted_dir.rglob("*") if p.is_file()]
    assert entries, f"no extracted files under {extracted_dir}"


def test_sample_path_mapping_json_parses(extracted_dir: Path):
    """A small, non-ALEAPP JSON artifact opens and parses as a real mapping.

    ``path_mapping.json`` is the extractor's index of obfuscated -> original
    paths: a lightweight, dependency-free sample that proves the extracted tree
    is genuine forensic output and not an empty stub.
    """
    mapping_file = extracted_dir / "path_mapping.json"
    if not mapping_file.is_file():
        pytest.skip(f"sample artifact {mapping_file.name} not present")

    data = json.loads(mapping_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data, "path_mapping.json is empty"

    # Every entry maps one path string to another path string.
    src, dst = next(iter(data.items()))
    assert isinstance(src, str) and src
    assert isinstance(dst, str) and dst
