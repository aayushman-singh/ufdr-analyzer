# DECISIONS — CiteSpan

The public product name is CiteSpan. The repository identity remains
aayushman-singh/ufdr-analyzer. Any ufdr-analyzer reference below is a
repository or legacy deployment reference.

Autonomous calls made by the orchestrator. Per HANDOFF rule 1, the user is never blocked; ambitious-path choices are logged here instead.

| # | Decision | Rationale | Reversible? |
|---|----------|-----------|-------------|
| 1 | Docker unavailable on this host → fix + statically validate compose, do NOT mark "boots cleanly" as verified. | Cannot install Docker non-interactively; static YAML/CMD correctness is the achievable bar. Runbook documents the boot command. | n/a |
| 2 | `.env` added to `.gitignore` immediately; live secrets left in local `.env` untouched but flagged for rotation. | `.env` held a live OpenRouter key + Neo4j Aura password and was tracked-eligible (`??`, not ignored). Stopping the leak is priority 0. I will NOT rotate keys myself (no creds), but flag loudly. | yes |
| 3 | `config.py` sources all secrets from env via `load_dotenv` + `_require()`; non-secret connection params (host/port/dbname) keep dev defaults. Missing secret → raise loudly (no silent default). | Honors "strip hardcoded creds" + user's no-fallback rule. `database.py` already prefers `DATABASE_URL` env, so this composes. | yes |
| 4 | Demo profile drops Neo4j + Celery/Redis + nginx; full-prod compose retained behind the original `docker-compose.yml`. Graph reads move to Postgres recursive CTE behind a `GRAPH_BACKEND` flag. | HANDOFF rule 2 deploy boundary — full stack won't run free-tier. | yes |
| 5 | LLM demo path uses the NL→IR pipeline; if no LLM key present, a deterministic stub planner is used **only when `DEMO_MODE=1` is explicitly set**, and it logs loudly that it is a stub. | Hosted demo must work without leaking a real key; the stub is explicit opt-in, not a silent fallback. | yes |

## Codex review of headline (codex/phase-bde.md) — triage

**Fixed this session (cheap + high-impact):**
- Reserved-word bug: `call`/`user` are PostgreSQL keywords → quoted all table identifiers in the compiler and entity service (SQLite tests didn't catch this).
- Audit event now records the typed plan + compiled SQL + result row ids (not just counts) — the chain now actually proves the NL→IR→SQL→rows claim.
- `database.py` `echo=True` removed (was leaking phone numbers/message text/params to logs); now `SQL_ECHO=1` opt-in only.
- Evidence export: `SECRET_KEY` check + PDF build moved BEFORE recording the export audit event (chain never claims a failed export); audit head hash folded into the signed content so the custody pointer is authenticated; signed payload widened to planner/total.
- `run_id` request fields typed `uuid.UUID` → invalid input is 422, not 500.
- Entity graph determinism: ORDER BY tie-breakers added; `degree` vs `hops` dual-semantics naming bug split into two fields.
- Honest docstrings: audit `record()` states it commits; HMAC is documented as a keyed integrity signature, not PKI.

**Accepted limitations (documented, out of scope for a portfolio demo — NOT production CJIS-grade):**
- **No authn/authz** on the new routes — anyone reaching the API can query/export. Needs JWT + run-ownership checks before any real deployment. (Backend has no auth layer yet repo-wide.)
- **HMAC ≠ PKI**: the signed PDF proves server-side integrity, not third-party-verifiable X.509 signing. Documented in `evidence_report.build_evidence_pdf`.
- **Audit chain `seq` race + no append-only DB enforcement**: `record()` computes `seq+1` without a unique constraint/lock; a privileged DB writer could rewrite the chain. Needs a unique constraint on `seq`, row-level locking, and ideally DB triggers / external anchoring.
- **No Alembic migration** for `audit_event` (schema is still `SQLModel.metadata.create_all`); repo-wide pre-existing gap.
- **Export re-runs the query** rather than exporting a frozen prior result — fine for the static demo case; a real system should export an immutable stored result snapshot.
- Timestamp round-trip across DB drivers could theoretically affect chain re-hash on Postgres (verified consistent on SQLite). Would store the exact hashed ISO string in prod.

## V2 — feature discovery (go big)

Brainstormed candidates, scored on (a) investigator value, (b) wow-for-hire, (c) one-session feasibility (no heavy deps / external services, testable on SQLite):

| Candidate | (a) | (b) | (c) | Verdict |
|---|---|---|---|---|
| **Temporal patterns & anomaly detection** (spikes, late-night, dropoff/cessation, bursts, new-contact emergence) + deterministic English narration | High | High | High | **SHIP #1** |
| **Cross-case entity linking** (salted-hash identifier index → "this number appears in N other cases") | High | High | High | **SHIP #2** |
| LLM-narrated timeline | Med | Med | High | Folded into #1 as a deterministic narrator (LLM-optional, not required) |
| Court-grade x509 + RFC-3161 TSA export | High | Med | Med | Deferred — directly answers the codex "HMAC≠PKI" critique but RFC-3161 needs a live TSA and is less demoable than #1/#2. Documented as next step. |
| Voice-note transcription + sentiment (faster-whisper) | Med | High | **Low** | Rejected this session — heavy ML model, needs the 395MB audio artifacts + a runtime we don't have; unverifiable here. |
| Risk-scoring / suspicious-entity ranking | Med | Med | High | Partially subsumed by #1 (anomaly severity) + #2; not built standalone. |

**Why these two:** #1 is the within-case behavioral lever ("activity with X ceased after March 4") an investigator actually reasons with; #2 is the across-case correlation ("I'd let this near a real case") that single-case tools lack. Both are deterministic, citation-backed, testable on SQLite, and demoable without an LLM key or cloud. #2's salted-hash index also keeps raw PII out of the shared index — deliberately avoiding the secret-leak class the original recon flagged.

## Blocked-on-user (carried to SESSION_SUMMARY.md)
- **ROTATE the OpenRouter API key and Neo4j Aura password** that were present in `.env` — treat as compromised.
- Fly.io + Vercel account/login, DNS — needed for real deploy (configs + runbook provided).
- Decide whether to scrub `test_comprehensive.ufdr` (395 MB) from git history (LFS migrate or `filter-repo`) before any public push.

## Dependency exposure assessment

The reviewed frontend lock audit reports 0 critical, 39 high, 9 moderate, and
1 low finding. A count of 0 critical does not prove complete safety.

The hosted demo uses a static Next export behind Nginx. It does not run a Next
server and it does not use Next image optimization. `electron` and
`electron-builder` are development dependencies and are not part of the hosted
runtime. The `react-d3-tree` dependency inherits a `uuid` buffer issue.

The retained maintenance security release is Next 15.5.27. The `react-d3-tree`
dependency uses `uuid.v4`; the external-buffer advisory concerns uuid v3, v5,
and v6, so that advisory path does not match the runtime call used by this
product. The CSS build inputs are trusted project files, not attacker-controlled
runtime CSS.

The audit counts do not prove zero risk. Remaining risk includes future
dependency changes, runtime configuration errors, and defects in the static
export or browser proof. The release gate must still run authentic lock
validation and the live user-flow proof.
