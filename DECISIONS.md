# DECISIONS — ufdr-analyzer

Autonomous calls made by the orchestrator. Per HANDOFF rule 1, the user is never blocked; ambitious-path choices are logged here instead.

| # | Decision | Rationale | Reversible? |
|---|----------|-----------|-------------|
| 1 | Docker unavailable on this host → fix + statically validate compose, do NOT mark "boots cleanly" as verified. | Cannot install Docker non-interactively; static YAML/CMD correctness is the achievable bar. Runbook documents the boot command. | n/a |
| 2 | `.env` added to `.gitignore` immediately; live secrets left in local `.env` untouched but flagged for rotation. | `.env` held a live OpenRouter key + Neo4j Aura password and was tracked-eligible (`??`, not ignored). Stopping the leak is priority 0. I will NOT rotate keys myself (no creds), but flag loudly. | yes |
| 3 | `config.py` sources all secrets from env via `load_dotenv` + `_require()`; non-secret connection params (host/port/dbname) keep dev defaults. Missing secret → raise loudly (no silent default). | Honors "strip hardcoded creds" + user's no-fallback rule. `database.py` already prefers `DATABASE_URL` env, so this composes. | yes |
| 4 | Demo profile drops Neo4j + Celery/Redis + nginx; full-prod compose retained behind the original `docker-compose.yml`. Graph reads move to Postgres recursive CTE behind a `GRAPH_BACKEND` flag. | HANDOFF rule 2 deploy boundary — full stack won't run free-tier. | yes |
| 5 | LLM demo path uses the NL→IR pipeline; if no LLM key present, a deterministic stub planner is used **only when `DEMO_MODE=1` is explicitly set**, and it logs loudly that it is a stub. | Hosted demo must work without leaking a real key; the stub is explicit opt-in, not a silent fallback. | yes |

## Blocked-on-user (carried to SESSION_SUMMARY.md)
- **ROTATE the OpenRouter API key and Neo4j Aura password** that were present in `.env` — treat as compromised.
- Fly.io + Vercel account/login, DNS — needed for real deploy (configs + runbook provided).
- Decide whether to scrub `test_comprehensive.ufdr` (395 MB) from git history (LFS migrate or `filter-repo`) before any public push.
