# HANDOFF V2 — ufdr-analyzer: go big

You are resuming the same session that finished Phase 1. You shipped: compose-stack fix, slim demo profile (no Neo4j/Celery), 21 backend tests, **the NL→typed-IR→cited-results pipeline**, hash-chained audit log + signed PDF, Fly/Vercel configs. `SESSION_SUMMARY.md` is written. **Don't redo any of that.**

## New mission
You've made the product credible. Now make it *startling*. Find 1–2 features that turn this from "student SIH winner" into "I'd let this near a real case." Senior forensic-tools reviewers, FAANG security teams, AI-startup hiring panels — pick the one that hurts most to ignore.

## Discovery protocol
1. Re-read `SESSION_SUMMARY.md` + `DECISIONS.md` so you don't repeat work.
2. Brainstorm 5+ candidates. Span: forensic gravitas, ML differentiation, demo-ability.
3. Score: (a) **does this make the product genuinely more valuable to an investigator**, (b) **wow-factor for hire**, (c) **feasible in one session**.
4. Document picks + rejections in `DECISIONS.md`.
5. Ship.

## Sparks (not orders)
- **Temporal anomaly detection** — communication spikes, late-night patterns, dropoff after a specific date. Surface as a "Patterns" panel in the dashboard.
- **Cross-case entity linking** — "this phone number appears in 3 prior cases." Needs a tiny meta-DB or a hash-of-identifier index.
- **LLM-narrated timeline** — generate a 1-paragraph English summary of what the data shows ("WhatsApp activity dropped 80% on March 4, coinciding with…").
- **Court-grade evidence bundle** — RFC 3161 trusted-timestamp on exports + x509 signed manifest (you have hash-chained audit, take it to TSA).
- **Voice-note transcription + sentiment** via faster-whisper local model — the demo dataset has audio.

## Operating rules (unchanged)
- Decide-don't-block. Bias ambitious.
- No fallbacks. Fail loudly.
- After each large refactor: codex exec brutal review → `codex/<timestamp>.md`. Apply criticisms.
- Use subagents in parallel.
- Watch out for the same secret-leak class — the original recon found OpenRouter + Neo4j Aura keys in history.

## End-of-session output
Write `SESSION_SUMMARY_V2.md`. Append to `DECISIONS.md`.

## Start
Begin discovery. Go big. Go.
