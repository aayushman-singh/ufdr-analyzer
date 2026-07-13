#!/usr/bin/env python3
"""Quick local smoke test for authenticated API flows (no secrets printed)."""

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
EMAIL = "release-test@ufdr.local"
PASSWORD = "TestPass123!"


def post(path: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main() -> int:
    try:
        token = post("/auth/login", {"email": EMAIL, "password": PASSWORD})[
            "access_token"
        ]
    except Exception:
        token = post(
            "/auth/signup",
            {"username": "Release Tester", "email": EMAIL, "password": PASSWORD},
        )["access_token"]

    # seed if needed
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    run_id = subprocess.check_output(
        [sys.executable, str(repo / "scripts/seed_demo_case.py"), EMAIL],
        text=True,
    ).strip()

    preview = post(
        "/query/plan/preview",
        {"question": "show chats mentioning bitcoin", "run_id": run_id},
        token,
    )
    assert preview.get("planner") == "stub", preview

    run = post(
        "/query/plan",
        {"question": "show chats mentioning bitcoin", "run_id": run_id},
        token,
    )
    assert run.get("total", 0) >= 1, run

    patterns = get(f"/analytics/patterns?run_id={run_id}", token)
    assert patterns.get("total_events", 0) >= 1, patterns

    links = get(f"/cross-case/links?run_id={run_id}", token)
    assert "link_count" in links, links

    graph = get(f"/link-graph?run_ids={run_id}&seed=%2B15551234567&hops=2", token)
    assert graph.get("seed_found") is True, graph

    print("OK", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
