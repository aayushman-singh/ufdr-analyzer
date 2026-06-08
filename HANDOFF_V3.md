# HANDOFF V3 — ufdr-analyzer: go bigger

You finished v1 (stack-fix, NL→IR pipeline, signed PDF) and V2 (temporal anomalies, PII-minimized cross-case linking). **Don't redo any of that.**

## New mission
Two more features that take this from "credible forensic tool" to "court-room-adjacent":
1. **RFC 3161 trusted timestamping** on the custody root hash. V2's audit chain is tamper-evident but locally-signed; an external Timestamp Authority makes the seal **independently verifiable**. Use `freetsa.org` or `digicert TSA` as a free-tier issuer.
2. **Voice-note transcription** via `faster-whisper` (local, no API key). UFDR dumps contain audio messages that are currently invisible to the query layer. Transcribe at ingest, index transcripts in Meili alongside text, link transcript → audio file via `extraction_metadata`.

## Rules
- Decide-don't-block. No fallbacks.
- Codex review per refactor.
- Don't ship a TSA call without a fallback that fails loud + records the exact reason (network down, TSA rejected) — but never a "skip and pretend it's signed" fallback.
- Voice transcripts must respect the audit chain — record `(audio_file_id, model, ts, transcript_hash)` as an audit event.
- Write `SESSION_SUMMARY_V3.md` when done.

Go big. Go.
