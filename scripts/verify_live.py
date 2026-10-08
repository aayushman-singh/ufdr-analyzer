"""Prove the CiteSpan end-user query flow with a clean browser session."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PROOF_ROOT = Path.home() / ".citespan" / "release-proof"
PLAYWRIGHT_BROWSERS_PATH = ROOT / ".venv" / "playwright-browsers"
CANONICAL_DEMO_RUN_ID = "11111111-1111-4111-8111-111111111111"


def _record_private_failure(step: str, exc: BaseException, state: dict[str, object]) -> Path:
    """Store sanitized traceback and verification state outside stdout."""
    EXTERNAL_PROOF_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(tempfile.mkdtemp(prefix="verification-failure-", dir=EXTERNAL_PROOF_ROOT))
    detail = _sanitize_failure_text(traceback.format_exc())
    path = evidence_dir / "failure.json"
    path.write_text(
        json.dumps(
            {"failed_step": step, "error": _sanitize_failure_text(str(exc)), "traceback": detail, "state": state},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _sanitize_failure_text(value: str) -> str:
    return re.sub(
        r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=<REDACTED>",
        value,
    )


def _validate_cited_response(response: dict) -> None:
    """Require actual rows with valid, in-snippet evidence spans."""
    if response.get("planner") != "stub":
        raise RuntimeError("query result does not identify the deterministic demo planner")
    rows = response.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("query result has no cited result rows")
    for row in rows:
        citations = row.get("citations") if isinstance(row, dict) else None
        if not isinstance(citations, list) or not citations:
            raise RuntimeError("query result has no evidence spans")
        for citation in citations:
            snippet = citation.get("snippet")
            matched_value = citation.get("matched_value")
            start = citation.get("char_start")
            end = citation.get("char_end")
            if (
                not isinstance(snippet, str)
                or not isinstance(matched_value, str)
                or not isinstance(start, int)
                or not isinstance(end, int)
            ):
                raise RuntimeError("query citation has invalid evidence span metadata")
            if start < 0 or end <= start or end > len(snippet):
                raise RuntimeError("query citation evidence span is outside its snippet")
            if snippet[start:end] != matched_value:
                raise RuntimeError("query citation evidence text does not match its character span")


def _assert_exported_routes_use_trailing_slash() -> None:
    config = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    if 'output: "export"' not in config or "trailingSlash: true" not in config:
        raise RuntimeError("live verification requires exported frontend routes with trailing slashes")


def _write_proof_artifacts(
    output_dir: Path,
    live_url: str,
    question: str,
    screenshots: list[str],
    observed_response: dict,
    deployment_id: str,
    upload_status: int = 403,
    ingestion_statuses: dict[str, int] | None = None,
    *,
    complete: bool = True,
) -> dict:
    """Write durable proof and the draft only after browser proof passes."""
    if complete is not True:
        raise RuntimeError("live proof is not complete")
    _validate_cited_response(observed_response)
    if upload_status != 403:
        raise RuntimeError("live proof requires the server-side upload mutation to return HTTP 403")
    if ingestion_statuses != {
        "/api/ingest/": 403,
        "/api/ingest/validate-path": 403,
        "/api/ingest/aleapp-structure": 403,
    }:
        raise RuntimeError("live proof requires every public ingestion boundary to return HTTP 403")
    screenshot_paths = [output_dir / item for item in screenshots]
    if not screenshots or any(not path.is_file() for path in screenshot_paths):
        raise RuntimeError("live proof requires existing browser screenshots")
    row_count = len(observed_response["rows"])
    citation_count = sum(len(row["citations"]) for row in observed_response["rows"])
    proof = {
        "complete": complete,
        "external_identity": live_url,
        "deployment_id": deployment_id,
        "live_url": live_url,
        "steps": [
            "Open the live HTTPS CiteSpan URL in a clean browser context.",
            "Create a new account with a unique proof email.",
            f"Ask: {question}",
            "Confirm Cited Results show evidence spans and character offsets.",
            "Open the upload page and confirm the visible synthetic-demo upload-disabled message.",
            "POST to the upload mutation and observe HTTP 403 with the demo policy error.",
            "POST harmless permitted input to the public ingestion boundary and observe HTTP 403.",
            "GET a harmless permitted path through path validation and observe HTTP 403.",
            "GET harmless permitted ALEAPP parameters and observe HTTP 403.",
            "Activate Reset to sample and observe HTTP 200 with the canonical synthetic run response.",
        ],
        "result": f"The clean session returned {row_count} cited result rows with {citation_count} evidence spans from the observed query response.",
        "screenshots": screenshots,
        "limits": [
            "The proof uses only the canonical synthetic demo run.",
            f"The hosted demo upload mutation returned HTTP {upload_status}.",
            "Every public ingestion boundary returned HTTP 403 before supplied paths or data were read.",
            "The deterministic demo planner is not a live large language model feature.",
        ],
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    proof_path = output_dir / "citespan-live-proof.md"
    post_path = output_dir / "citespan-launch-post.md"
    launch_post = (
        "I built CiteSpan, a forensic evidence workbench for questions over a "
        "canonical synthetic UFDR sample.\n\n"
        f"A clean session at {live_url} created an account, reset access to the "
        "sample, asked a natural-language question, and returned cited results "
        "linked to evidence spans and character offsets.\n\n"
        "The hosted demo uses synthetic data only. File upload is disabled. "
        "The demo planner is deterministic and is not a live large language "
        "model feature.\n"
    )
    proof_path.write_text(
        "# CiteSpan live proof\n\n"
        "Status: passed by browser verification.\n\n"
        f"## Live URL\n\n{live_url}\n\n"
        f"## Deployment identity\n\n`{deployment_id}`\n\n"
        "## Exact user steps\n\n"
        + "\n".join(f"{index}. {step}" for index, step in enumerate(proof["steps"], 1))
        + "\n\n## Observed result\n\n"
        + proof["result"]
        + "\n\n## Screenshots\n\n"
        + "\n".join(f"- `{output_dir / item}`" for item in screenshots)
        + "\n\n## Limits\n\n"
        + "\n".join(f"- {item}" for item in proof["limits"])
        + "\n",
        encoding="utf-8",
    )
    post_path.write_text(launch_post, encoding="utf-8")
    proof.update(
        {
            "proof_path": str(proof_path),
            "launch_post_path": str(post_path),
            "launch_post": launch_post,
            "screenshot_paths": [str(output_dir / item) for item in screenshots],
        }
    )
    return proof


def _run_browser_flow(playwright, live_url: str, run_id: str, question: str, output_dir: Path) -> dict:
    """Execute the visible clean-session flow and return its observed query response."""
    if run_id != CANONICAL_DEMO_RUN_ID:
        raise RuntimeError("live verification requires the canonical synthetic demo run ID")
    email = f"citespan-proof-{uuid.uuid4().hex}@example.invalid"
    password = f"Proof-{uuid.uuid4().hex}!"
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    query_response: dict | None = None

    def capture_query_response(response) -> None:
        nonlocal query_response
        if response.request.method == "POST" and response.url.rstrip("/").endswith("/query/plan"):
            query_response = response.json()

    page.on("response", capture_query_response)
    parsed = urlsplit(live_url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    expected_query_url = f"{origin}/query-plan/"
    try:
        page.goto(live_url, wait_until="networkidle")
        if "CiteSpan" not in page.title() and "CiteSpan" not in page.locator("body").inner_text():
            raise RuntimeError("live page does not identify as CiteSpan")
        page.screenshot(path=str(output_dir / "citespan-home.png"), full_page=True)
        page.goto(f"{origin}/upload/", wait_until="networkidle")
        if page.get_by_text("Upload disabled in the synthetic demo", exact=False).count() != 1:
            raise RuntimeError("upload page does not visibly state that upload is disabled")
        if page.locator("input[type='file']").count() != 0:
            raise RuntimeError("upload page exposes a file input in the hosted demo")
        upload_response = page.request.post(f"{origin}/api/upload/", data={"file": "forbidden"})
        if upload_response.status != 403:
            raise RuntimeError(f"upload mutation was not rejected with HTTP 403: {upload_response.status}")
        if "disabled in demo mode" not in upload_response.text().lower():
            raise RuntimeError("upload mutation rejection did not identify the demo policy")
        ingestion_responses = {
            "/api/ingest/": page.request.post(
                f"{origin}/api/ingest/", data={"file_path": "permitted-test-input.ufdr"}
            ),
            "/api/ingest/validate-path": page.request.get(
                f"{origin}/api/ingest/validate-path", params={"file_path": "permitted-test-input.ufdr"}
            ),
            "/api/ingest/aleapp-structure": page.request.get(
                f"{origin}/api/ingest/aleapp-structure",
                params={"report_path": "permitted-test-input", "run_id": run_id},
            ),
        }
        ingestion_statuses = {path: response.status for path, response in ingestion_responses.items()}
        if ingestion_statuses != {path: 403 for path in ingestion_responses}:
            raise RuntimeError(
                f"public ingestion boundary was not rejected with HTTP 403: {ingestion_statuses}"
            )
        page.screenshot(path=str(output_dir / "citespan-upload-disabled.png"), full_page=True)
        page.goto(f"{origin}/signup/", wait_until="networkidle")
        page.locator("#name").fill("CiteSpan proof user")
        page.locator("#email").fill(email)
        page.locator("#password").fill(password)
        page.locator("#confirmPassword").fill(password)
        page.locator("#terms").check()
        page.get_by_role("button", name="Create Account").click()
        page.wait_for_url(expected_query_url, wait_until="networkidle")
        if page.url != expected_query_url:
            raise RuntimeError(f"signup reached an unexpected query route: {page.url}")
        page.goto(f"{origin}/upload/", wait_until="networkidle")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.rstrip("/").endswith("/api/demo/reset")
        ) as reset_event:
            page.get_by_role("button", name="Reset to sample").click()
        reset_response = reset_event.value
        if reset_response.status != 200:
            raise RuntimeError(f"demo reset failed with HTTP {reset_response.status}")
        reset_body = reset_response.json()
        if reset_body != {
            "run_id": run_id,
            "sample": "canonical synthetic UFDR",
            "reset": True,
        }:
            raise RuntimeError("demo reset did not return the canonical synthetic sample")
        page.wait_for_url(expected_query_url, wait_until="networkidle")
        if page.url != expected_query_url:
            raise RuntimeError(f"reset reached an unexpected query route: {page.url}")
        page.get_by_role("status", name="Sample loaded: canonical synthetic UFDR.").wait_for()
        if page.locator("#run-id").input_value() != run_id:
            raise RuntimeError("demo reset returned the wrong canonical run")
        page.locator("#question").fill(question)
        page.get_by_role("button", name="Run query").click()
        page.get_by_text("Cited Results", exact=True).wait_for()
        if query_response is None:
            raise RuntimeError("query response was not observed from the visible query action")
        _validate_cited_response(query_response)
        if page.get_by_text(re.compile(r"planner: deterministic demo planner")).count() == 0:
            raise RuntimeError("query result does not identify the deterministic demo planner")
        if page.locator("[data-testid='cited-result-row']").count() == 0:
            raise RuntimeError("query result has no cited result rows")
        if page.locator(".cite").count() == 0:
            raise RuntimeError("query result has no highlighted evidence spans")
        if page.locator("text=chars ").count() == 0:
            raise RuntimeError("query result has no citation character offsets")
        expected_evidence = [
            citation["snippet"][citation["char_start"] : citation["char_end"]]
            for row in query_response["rows"]
            for citation in row["citations"]
        ]
        if page.locator(".cite").all_inner_texts() != expected_evidence:
            raise RuntimeError("visible evidence spans do not match the observed query response")
        page.screenshot(path=str(output_dir / "citespan-query-results.png"), full_page=True)
        return {
            "query_response": query_response,
            "upload_status": upload_response.status,
            "ingestion_statuses": ingestion_statuses,
        }
    finally:
        context.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("CITESPAN_URL"))
    parser.add_argument("--run-id", default=os.environ.get("CITESPAN_DEMO_RUN_ID"))
    parser.add_argument("--deployment-id", default=os.environ.get("CITESPAN_DEPLOYMENT_ID"))
    parser.add_argument("--question", default="Show me all WhatsApp messages mentioning a bank transfer")
    parser.add_argument(
        "--output-dir",
        default=None,
    )
    args = parser.parse_args()
    if not args.url or not args.url.startswith("https://"):
        raise ValueError("--url must be the live HTTPS CiteSpan URL")
    if not args.run_id:
        raise ValueError("--run-id must identify the canonical synthetic demo run")
    if args.run_id != CANONICAL_DEMO_RUN_ID:
        raise ValueError("--run-id must equal the canonical synthetic demo run ID")
    if not args.deployment_id:
        raise ValueError("--deployment-id must identify the observed deployment")
    _assert_exported_routes_use_trailing_slash()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("live verification requires the project Playwright dependency") from exc
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else EXTERNAL_PROOF_ROOT / f"manual-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    proof_path = output_dir / "citespan-live-proof.md"
    post_path = output_dir / "citespan-launch-post.md"
    screenshot_paths = [
        output_dir / "citespan-home.png",
        output_dir / "citespan-query-results.png",
        output_dir / "citespan-upload-disabled.png",
    ]
    for path in [proof_path, post_path, *screenshot_paths]:
        path.unlink(missing_ok=True)
    try:
        with sync_playwright() as playwright:
            observed = _run_browser_flow(
                playwright, args.url, args.run_id, args.question, output_dir
            )
    except Exception:
        for path in [proof_path, post_path, *screenshot_paths]:
            path.unlink(missing_ok=True)
        raise

    proof = _write_proof_artifacts(
        output_dir,
        args.url,
        args.question,
        [
            "citespan-home.png",
            "citespan-upload-disabled.png",
            "citespan-query-results.png",
        ],
        observed["query_response"],
        args.deployment_id,
        observed["upload_status"],
        observed["ingestion_statuses"],
    )
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        evidence = _record_private_failure(
            " ".join(sys.argv[1:]) or "verify_live",
            exc,
            {
                "url": os.environ.get("CITESPAN_URL", "<not-provided>"),
                "run_id": os.environ.get("CITESPAN_DEMO_RUN_ID", "<not-provided>"),
            },
        )
        print(json.dumps({"complete": False, "error": _sanitize_failure_text(str(exc)), "failure_evidence": str(evidence)}))
        print(f"live verification failed; evidence={evidence}\n{traceback.format_exc()}", file=sys.stderr)
        raise SystemExit(1)
