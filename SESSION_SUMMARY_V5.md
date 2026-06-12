# SESSION_SUMMARY_V5

## RBAC Model

- `Run.user_id` remains the implicit case owner.
- `CaseMembership` grants explicit `owner` or `viewer` access to a case.
- Server-side authorization is enforced through `authorize_run` / `authorize_runs` before any case data is returned.
- Covered case-data routes include link graph, query plan/legacy query, exports/reports, analytics/entities/transcription, ALEAPP structure, uploads tied to cases, and cross-case results.
- Admin-only routes: audit chain operations and Postgres-to-Neo4j sync.
- Cross-case links are redacted to runs visible to the caller; unauthorized linked cases are not returned as empty oracle hints.
- Upload and ALEAPP structure routes require authentication and case-bound filesystem paths.

## Performance Measurements

Command:

```powershell
./.venv-test/Scripts/python.exe backend/perf/bench_v5.py --runs 40 --msgs 5000 --reps 5
```

Dataset: 40 synthetic cases, 5,000 messages each, 200,000 message rows total.

| Hot path | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Graph build | 88.72ms | 69.76ms | 1.3x |
| Query execution | 29.33ms | 1.89ms | 15.5x |

Query plan evidence:

- Before: `SCAN message | USE TEMP B-TREE FOR ORDER BY`
- After: `SEARCH message USING INDEX ix_message_run_ts (run_id=?)`

Indexes added for measured hot paths include run/timestamp and run/source lookups used by query and graph traversal.
Graph output is capped with deterministic ordering and explicit truncation metadata instead of eagerly materializing an unbounded case graph.
Query plans now carry offset/limit through compilation and execution so large result sets are paginated.

## Proof

- `ruff check --fix . && ruff format .`
  - Required repo-wide command was run.
  - It still fails on pre-existing ALEAPP/legacy lint debt outside the V5 scope after applying automatic fixes.
  - Unrelated automatic formatting churn was discarded.
- Targeted changed-file Ruff gate: passed.
- Backend tests:

```powershell
./.venv-test/Scripts/python.exe -m pytest backend/tests -q
```

Result: `153 passed, 1 warning`.

- Senior review command:

```powershell
codex exec --skip-git-repo-check "brutal senior security + perf review -- authz bypass, injection, no-fallback, perf-claim honesty"
```

Result: an earlier run produced findings that were applied. The final rerun failed locally with a Codex usage-limit error; the failure and a clearly labeled diff-only fallback review are saved in `codex/v5-senior-review.txt`.

## Non-Claims And Residual Risk

- The benchmark is SQLite synthetic data, not a production Postgres benchmark.
- The graph speedup is modest; the stronger performance win is bounded deterministic graph materialization and query pagination.
- Seeded phone expansion uses bounded frontier scanning plus canonical digit matching; it is not a full normalized participant index.
- Ingestion database writes now fail loud and avoid partial DB commits, but external systems such as embeddings, Meili, and object storage are not transactionally rolled back by SQLModel.
- Repo-wide Ruff remains blocked by legacy ALEAPP debt outside this security/performance scope.
- Frontend was not touched; backend removed the unmounted legacy raw graph router and preserved the V5 link-graph API.
- The final exact senior-review rerun could not complete because of local Codex usage limits, so the final review artifact is labeled accordingly.
