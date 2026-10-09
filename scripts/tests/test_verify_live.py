import json
import errno
import os
import stat
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_live


ROOT = Path(__file__).resolve().parents[2]


def _remove_owned_fixture(path: Path, label: str) -> None:
    root = path.resolve()

    def normalize_permissions():
        if not path.exists():
            return
        for directory, directory_names, file_names in os.walk(path, topdown=True, followlinks=False):
            directory_path = Path(directory)
            resolved_directory = directory_path.resolve(strict=False)
            if resolved_directory != root and root not in resolved_directory.parents:
                raise RuntimeError(f"{label} cleanup failed: path escapes fixture root {root}: {directory_path}")
            os.chmod(directory_path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            for name in sorted(directory_names + file_names):
                candidate = directory_path / name
                resolved = candidate.resolve(strict=False)
                if resolved != root and root not in resolved.parents:
                    raise RuntimeError(f"{label} cleanup failed: path escapes fixture root {root}: {candidate}")
                if candidate.is_symlink():
                    continue
                mode = stat.S_IWRITE | stat.S_IREAD
                if candidate.is_dir():
                    mode |= stat.S_IEXEC
                os.chmod(candidate, mode)

    def cleanup_error(operation, failed_path, exc_info):
        candidate = Path(failed_path).resolve(strict=False)
        error = exc_info[1]
        if candidate != root and root not in candidate.parents:
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: path escapes fixture root {root}"
            ) from error
        if not isinstance(error, OSError) or error.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: {error}"
            ) from error
        print(
            f"{label} cleanup correction: operation={operation.__name__} path={candidate} "
            f"error_type={type(error).__name__} error={error}",
            file=sys.stderr,
            flush=True,
        )
        try:
            mode = stat.S_IWRITE | stat.S_IREAD
            if candidate.is_dir():
                mode |= stat.S_IEXEC
            os.chmod(candidate, mode)
            operation(failed_path)
        except Exception as retry_error:
            raise RuntimeError(
                f"{label} cleanup failed: operation={operation.__name__} path={candidate}: retry failed: {retry_error}"
            ) from retry_error

    try:
        normalize_permissions()
        shutil.rmtree(path, onerror=cleanup_error)
    except Exception as exc:
        raise RuntimeError(f"{label} cleanup failed: operation=rmtree path={path}: {exc}") from exc
    if path.exists():
        raise RuntimeError(f"{label} cleanup failed: operation=rmtree path={path}: path remains")


def test_live_verifier_failure_returns_one_json_object_and_private_evidence():
    evidence_root = Path(tempfile.mkdtemp(prefix="citespan-verification-test-"))
    try:
        with patch.object(verify_live, "EXTERNAL_PROOF_ROOT", evidence_root):
            try:
                raise RuntimeError("query step failed")
            except RuntimeError as exc:
                evidence = verify_live._record_private_failure(
                    "query", exc, {"url": "https://citespan.example"}
                )
        assert evidence.is_file()
        detail = json.loads(evidence.read_text(encoding="utf-8"))
        assert detail["failed_step"]
        assert detail["traceback"]
    finally:
        _remove_owned_fixture(evidence_root, "verification fixture")


class _FakeLocator:
    def __init__(self, value=None, texts=None, actions=None, action=None):
        self.value = value
        self.texts = texts or []
        self.actions = actions
        self.action = action
        self.filled = None

    def fill(self, value):
        self.filled = value
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, value))

    def check(self):
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, True))
        return None

    def click(self):
        if self.actions is not None and self.action is not None:
            self.actions.append((self.action, True))
        return None

    def wait_for(self):
        return None

    def input_value(self):
        return self.value

    def count(self):
        return len(self.texts)

    def all_inner_texts(self):
        return self.texts

    def inner_text(self):
        return "CiteSpan"


class _FakePage:
    def __init__(self):
        self.title_value = "CiteSpan"
        self.actions = []
        self.query_response = {
            "planner": "stub",
            "rows": [
                {
                    "source_table": "aleappartifact",
                    "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                    "citations": [
                        {
                            "source_table": "aleappartifact",
                            "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                            "column": "filename",
                            "snippet": "whatsapp_messages.csv",
                            "matched_value": "whatsapp",
                            "char_start": 0,
                            "char_end": 8,
                        }
                    ]
                }
            ],
        }
        self.request = _FakeRequest()
        self.url = ""
        self.reset_response_observed = False
        self.reset_response_status = 200
        self.reset_response_body = {
            "run_id": verify_live.CANONICAL_DEMO_RUN_ID,
            "sample": "canonical synthetic UFDR",
            "reset": True,
        }

    def goto(self, url, wait_until):
        self.url = url
        return None

    def wait_for_url(self, pattern, wait_until):
        self.url = pattern
        return None

    def title(self):
        return self.title_value

    def locator(self, selector):
        values = {
            "body": _FakeLocator(),
            "#name": _FakeLocator(actions=self.actions, action=selector),
            "#email": _FakeLocator(actions=self.actions, action=selector),
            "#password": _FakeLocator(actions=self.actions, action=selector),
            "#confirmPassword": _FakeLocator(actions=self.actions, action=selector),
            "#terms": _FakeLocator(actions=self.actions, action=selector),
            "#run-id": _FakeLocator(verify_live.CANONICAL_DEMO_RUN_ID),
            "#question": _FakeLocator(actions=self.actions, action=selector),
            "[data-testid='cited-result-row']": _FakeLocator(texts=["row"]),
        ".cite": _FakeLocator(texts=["whatsapp"]),
            "text=chars ": _FakeLocator(texts=["chars 0-4"]),
        }
        return values.get(selector, _FakeLocator())

    def get_by_role(self, role, name):
        return _FakeLocator(actions=self.actions, action=(role, name))

    def get_by_text(self, text, exact=False):
        if isinstance(text, str) and (
            text == "Cited Results"
            or "planner:" in text
            or "Upload disabled in the synthetic demo" in text
        ):
            return _FakeLocator(texts=["visible"])
        if hasattr(text, "pattern") and "planner:" in text.pattern:
            return _FakeLocator(texts=["visible"])
        return _FakeLocator()

    def screenshot(self, path, full_page):
        Path(path).write_bytes(b"screenshot")

    def on(self, event, callback):
        if event == "response":
            callback(_FakeResponse(self.query_response))

    def expect_response(self, predicate):
        return _FakeResetExpectation(self, predicate)


class _FakeResetExpectation:
    def __init__(self, page, predicate):
        self.page = page
        self.predicate = predicate
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        response = _FakeResetResponse(
            self.page.reset_response_status,
            self.page.reset_response_body,
        )
        if not self.predicate(response):
            raise AssertionError("reset response did not match the expected request")
        self.value = response
        self.page.reset_response_observed = True
        return False


class _FakeResponse:
    def __init__(self, payload):
        self.request = type("Request", (), {"method": "POST"})()
        self.url = "https://citespan.example/api/query/plan"
        self._payload = payload

    def json(self):
        return self._payload


class _FakeUploadResponse:
    status = 403

    def text(self):
        return "File upload and path ingestion are disabled in demo mode."


class _FakeResetResponse:
    request = type("Request", (), {"method": "POST"})()
    url = "https://citespan.example/api/demo/reset"

    def __init__(self, status, body):
        self.status = status
        self.body = body

    def json(self):
        return self.body


class _FakeRequest:
    def post(self, url, data):
        return _FakeUploadResponse()

    def get(self, url, params):
        return _FakeUploadResponse()


class _FakeContext:
    def new_page(self):
        return _FakePage()

    def close(self):
        return None


class _FakeBrowser:
    def new_context(self):
        return _FakeContext()

    def close(self):
        return None


class _FakePlaywright:
    class chromium:
        @staticmethod
        def launch(headless):
            return _FakeBrowser()


def test_browser_flow_proves_clean_session_and_cited_evidence(tmp_path):
    page = _FakePage()

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    result = verify_live._run_browser_flow(
        _PagePlaywright(),
        "https://citespan.example",
        verify_live.CANONICAL_DEMO_RUN_ID,
        "Show bank transfers",
        tmp_path,
    )

    assert result["query_response"]["planner"] == "stub"
    assert result["query_response"]["rows"][0]["citations"][0]["matched_value"] == "whatsapp"
    assert result["upload_status"] == 403
    assert result["ingestion_statuses"] == {
        "/api/ingest/": 403,
        "/api/ingest/validate-path": 403,
        "/api/ingest/aleapp-structure": 403,
    }
    assert (tmp_path / "citespan-home.png").is_file()
    assert (tmp_path / "citespan-upload-disabled.png").is_file()
    assert (tmp_path / "citespan-query-results.png").is_file()
    assert (("button", "Create Account"), True) in page.actions
    assert (("button", "Reset to sample"), True) in page.actions
    assert page.reset_response_observed is True
    assert (("button", "Run query"), True) in page.actions
    assert ("#question", "Show bank transfers") in page.actions


def test_browser_flow_rejects_noncanonical_run_id_before_browser_launch(tmp_path):
    class _BrowserMustNotLaunch:
        class chromium:
            @staticmethod
            def launch(headless):
                raise AssertionError("browser must not launch for a noncanonical run")

    with pytest.raises(RuntimeError, match="canonical synthetic demo run ID"):
        verify_live._run_browser_flow(
            _BrowserMustNotLaunch(),
            "https://citespan.example",
            "not-canonical",
            "Show bank transfers",
            tmp_path,
        )


def test_browser_flow_rejects_noncanonical_reset_response(tmp_path):
    page = _FakePage()
    page.reset_response_body["run_id"] = "not-canonical"

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    with pytest.raises(RuntimeError, match="canonical synthetic sample"):
        verify_live._run_browser_flow(
            _PagePlaywright(),
            "https://citespan.example",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "Show bank transfers",
            tmp_path,
        )


def test_browser_flow_stops_on_reset_http_failure(tmp_path):
    page = _FakePage()
    page.reset_response_status = 503

    class _PageContext:
        def new_page(self):
            return page

        def close(self):
            return None

    class _PageBrowser:
        def new_context(self):
            return _PageContext()

        def close(self):
            return None

    class _PagePlaywright:
        class chromium:
            @staticmethod
            def launch(headless):
                return _PageBrowser()

    with pytest.raises(RuntimeError, match="demo reset failed with HTTP 503"):
        verify_live._run_browser_flow(
            _PagePlaywright(),
            "https://citespan.example",
            verify_live.CANONICAL_DEMO_RUN_ID,
            "Show bank transfers",
            tmp_path,
        )


def test_upload_reset_control_has_authenticated_canonical_request_and_error_gate():
    source = (ROOT / "frontend" / "app" / "upload" / "page.tsx").read_text(
        encoding="utf-8"
    )
    start = source.index("const handleResetToSample = async () => {")
    end = source.index("\n\n  return (", start)
    handler = source[start:end]
    assert 'authedFetch("/api/demo/reset"' in handler
    assert 'method: "POST"' in handler
    assert 'credentials: "include"' in handler
    assert 'body.run_id !== "11111111-1111-4111-8111-111111111111"' in handler
    assert 'body.sample !== "canonical synthetic UFDR"' in handler
    assert "body.reset !== true" in handler
    assert 'localStorage.setItem("citespan.demo.run_id", body.run_id)' in handler
    assert handler.index("router.push(\"/query-plan/\")") > handler.index(
        'body.reset !== true'
    )
    assert "setResetError" in handler
    assert "setResetError" in handler[handler.index("} catch"):]
    assert "router.push" not in handler[handler.index("} catch"):]


def test_live_verification_rejects_non_https_urls():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_live.py"), "--url", "http://localhost:3000", "--run-id", "demo"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "HTTPS" in value["error"]


def test_live_verification_rejects_noncanonical_run_id_from_cli(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_live.py"),
            "--url",
            "https://citespan.example",
            "--run-id",
            "not-canonical",
            "--deployment-id",
            "citespan-test",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    value = json.loads(result.stdout)
    assert result.returncode != 0
    assert value["complete"] is False
    assert "canonical synthetic demo run ID" in value["error"]


def test_live_verification_default_output_is_script_relative():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "EXTERNAL_PROOF_ROOT" in source
    assert "new_context" in source


def test_citation_validation_requires_evidence_spans_and_offsets():
    verify_live._validate_cited_response(
        {
            "planner": "stub",
            "rows": [
                {
                    "source_table": "aleappartifact",
                    "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                    "citations": [
                        {
                            "source_table": "aleappartifact",
                            "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                            "column": "category",
                            "snippet": "WhatsApp messages",
                            "matched_value": "WhatsApp",
                            "char_start": 0,
                            "char_end": 8,
                        }
                    ]
                }
            ],
        }
    )


def test_citation_validation_rejects_results_without_evidence_spans():
    with pytest.raises(RuntimeError, match="evidence spans"):
        verify_live._validate_cited_response(
            {
                "planner": "stub",
                "rows": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "citations": [],
                    }
                ],
            }
        )


def test_live_verification_source_resets_demo_before_query_and_writes_post_conditionally():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert 'get_by_role("button", name="Reset to sample")' in source
    assert "citespan-launch-post.md" in source


def test_live_verification_uses_same_origin_api_and_trailing_slash_query_route():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "/api/upload/" in source
    assert "/api/ingest/aleapp-structure" in source
    assert "ingestion_statuses" in source
    assert "expected_query_url" in source
    assert "page.url != expected_query_url" in source


def test_frontend_export_keeps_trailing_slash_routes():
    source = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")

    assert 'output: "export"' in source
    assert "trailingSlash: true" in source


def test_live_verification_uses_only_visible_browser_controls():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "page.evaluate" not in source
    assert 'get_by_role("button", name="Reset to sample")' in source
    assert 'page.locator("#run-id").fill' not in source


def test_live_verification_validates_the_observed_query_response():
    source = (ROOT / "scripts" / "verify_live.py").read_text(encoding="utf-8")

    assert "query_response" in source
    assert "_validate_cited_response(query_response, run_id)" in source
    assert "visible evidence spans do not match" in source


def test_proof_writer_returns_exact_durable_paths_and_draft(tmp_path):
    (tmp_path / "citespan-home.png").write_bytes(b"home")
    (tmp_path / "citespan-query-results.png").write_bytes(b"results")
    result = verify_live._write_proof_artifacts(
        tmp_path,
        "https://citespan.example",
        "Show bank transfers",
        ["citespan-home.png", "citespan-query-results.png"],
        {
            "planner": "stub",
            "rows": [
                {
                    "source_table": "aleappartifact",
                    "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                    "citations": [
                        {
                            "source_table": "aleappartifact",
                            "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                            "column": "category",
                            "snippet": "WhatsApp messages",
                            "matched_value": "WhatsApp",
                            "char_start": 0,
                            "char_end": 8,
                        }
                    ]
                }
            ],
        },
        "citespan-test",
        ingestion_statuses={
            "/api/ingest/": 403,
            "/api/ingest/validate-path": 403,
            "/api/ingest/aleapp-structure": 403,
        },
    )

    assert result["proof_path"] == str(tmp_path / "citespan-live-proof.md")
    assert result["launch_post_path"] == str(tmp_path / "citespan-launch-post.md")
    assert result["launch_post"] == (tmp_path / "citespan-launch-post.md").read_text()
    proof_text = (tmp_path / "citespan-live-proof.md").read_text()
    launch_post_text = (tmp_path / "citespan-launch-post.md").read_text()
    assert "## Deployment identity" in proof_text
    assert "citespan-test" in proof_text
    assert "citespan-test" not in launch_post_text
    assert all(path.startswith(str(tmp_path)) for path in result["screenshot_paths"])
    assert all(Path(path).is_file() for path in result["screenshot_paths"])
    assert Path(result["proof_path"]).is_file()
    assert Path(result["launch_post_path"]).is_file()


def test_proof_writer_does_not_write_when_proof_is_incomplete(tmp_path):
    observed = {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "column": "category",
                        "snippet": "WhatsApp messages",
                        "matched_value": "WhatsApp",
                        "char_start": 0,
                        "char_end": 8,
                    }
                ]
            }
        ],
    }
    with pytest.raises(RuntimeError, match="not complete"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            [],
            observed,
            "citespan-test",
            complete=False,
        )
    assert not (tmp_path / "citespan-live-proof.md").exists()
    assert not (tmp_path / "citespan-launch-post.md").exists()


def test_proof_writer_rejects_missing_screenshot_files(tmp_path):
    observed = {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                        "column": "category",
                        "snippet": "WhatsApp messages",
                        "matched_value": "WhatsApp",
                        "char_start": 0,
                        "char_end": 8,
                    }
                ]
            }
        ],
    }
    with pytest.raises(RuntimeError, match="existing browser screenshots"):
        verify_live._write_proof_artifacts(
            tmp_path,
            "https://citespan.example",
            "Q",
            ["missing.png"],
            observed,
            "citespan-test",
            ingestion_statuses={
                "/api/ingest/": 403,
                "/api/ingest/validate-path": 403,
                "/api/ingest/aleapp-structure": 403,
            },
        )


def _canonical_artifact_response(**citation_overrides):
    citation = {
        "source_table": "aleappartifact",
        "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
        "column": "category",
        "snippet": "WhatsApp messages",
        "matched_value": "WhatsApp",
        "char_start": 0,
        "char_end": 8,
    }
    citation.update(citation_overrides)
    return {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID,
                "citations": [citation],
            }
        ],
    }


def test_citation_validation_rejects_internally_consistent_invented_row():
    response = _canonical_artifact_response(
        source_table="message",
        row_id="99999999-9999-4999-8999-999999999999",
        column="content",
        snippet="invented evidence",
        matched_value="invented",
        char_end=8,
    )
    response["rows"][0]["source_table"] = "message"
    response["rows"][0]["row_id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(RuntimeError, match="unknown canonical evidence row"):
        verify_live._validate_cited_response(response)


def test_citation_validation_rejects_altered_canonical_content():
    with pytest.raises(RuntimeError, match="snippet does not equal canonical evidence"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(snippet="WhatsApp altered")
        )


def test_citation_validation_accepts_canonical_artifact_columns_and_compact_uuid():
    artifact_id = verify_live.CANONICAL_DEMO_ARTIFACT_ROW_ID.replace("-", "")
    response = {
        "planner": "stub",
        "rows": [
            {
                "source_table": "aleappartifact",
                "row_id": artifact_id,
                "citations": [
                    {
                        "source_table": "aleappartifact",
                        "row_id": artifact_id,
                        "column": "filename",
                        "snippet": "whatsapp_messages.csv",
                        "matched_value": "whatsapp",
                        "char_start": 0,
                        "char_end": 8,
                    },
                    {
                        "source_table": "aleappartifact",
                        "row_id": artifact_id,
                        "column": "file_path",
                        "snippet": "/synthetic/whatsapp_messages.csv",
                        "matched_value": "whatsapp",
                        "char_start": 11,
                        "char_end": 19,
                    },
                ],
            }
        ],
    }
    verify_live._validate_cited_response(response)


def test_citation_validation_rejects_wrong_run_or_case_identity():
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(), expected_run_id="wrong-run"
        )


def test_citation_validation_rejects_invalid_offsets_and_mismatched_snippets():
    with pytest.raises(RuntimeError, match="outside its snippet"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(char_start=20, char_end=21)
        )
    with pytest.raises(RuntimeError, match="does not match its character span"):
        verify_live._validate_cited_response(
            _canonical_artifact_response(matched_value="messages")
        )


def test_citation_validation_fails_closed_when_manifest_is_missing_or_ambiguous(monkeypatch):
    monkeypatch.setattr(verify_live, "CANONICAL_EVIDENCE_MANIFEST", None)
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(_canonical_artifact_response())

    monkeypatch.setattr(
        verify_live,
        "CANONICAL_EVIDENCE_MANIFEST",
        {"run_id": verify_live.CANONICAL_DEMO_RUN_ID, "case_id": verify_live.CANONICAL_DEMO_RUN_ID, "rows": {}},
    )
    with pytest.raises(RuntimeError, match="canonical evidence manifest"):
        verify_live._validate_cited_response(_canonical_artifact_response())
