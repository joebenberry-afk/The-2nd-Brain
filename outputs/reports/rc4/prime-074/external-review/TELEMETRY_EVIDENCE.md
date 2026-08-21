# TELEMETRY_EVIDENCE.md (freshly re-inspected this review pass)

## Target artifact

Path: telemetry/agent-performance/01a02107-1a9d-73ef-8dfb-e8239b63dada.jsonl
(the prior qualification's "compat session" telemetry file)

Freshly recomputed this pass (not copied from the prior report):
- File size: 355,123 bytes
- SHA-256: 76e093ae8ee5b77de22e19231b2b970125be71dec4c57cbc6b037b3e394d6e34
- **Record count, recomputed by direct line-by-line JSON parse: 382**
  -- this CONFIRMS the prior report's "382-record" claim exactly; it was
  independently recomputed, not trusted.
- First record: `2026-08-20T21:15:17.551Z`, kind `prime_tool_surface`
  (a clean session start, not a truncated/mid-stream file).
- Last record: `2026-08-20T21:36:23.143Z`, kind `session_shutdown` (a
  clean, orderly session end -- no evidence of truncation or corruption).
- All 382 records carry the SAME single session id
  (`01a02107-1a9d-73ef-8dfb-e8239b63dada`) -- no cross-session records
  bled into this file.

## Limitation (preserved honestly, per the task's own instruction)

This independently re-verifies the PRIOR qualification session's real
telemetry artifact. It does **not** by itself prove that THIS external
review pass freshly exercised a brand-new session with fresh natural
compaction, or a brand-new fresh live isolated-instance run end-to-end --
see REVIEW_SUMMARY.md for why a fully fresh live isolated-0.7.4 session
was not re-executed in this specific review pass (a genuine, reproducible
RLM sub-agent kernel-bootstrap infrastructure blocker was encountered;
documented there). The RTD artifact hash (Phase E3-equivalent) WAS
independently, freshly recomputed this pass (see below) even though the
full live session was not re-run from scratch.

## RTD artifact byte-exact recovery, freshly recomputed this pass

Artifact sha256 (from the prior session's real rtd_shadow event):
  8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218

Command run fresh this pass:
  .venv\Scripts\python.exe -m second_brain artifact expand
  8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218

Result: exit 0, recovered exactly 66,016 bytes, recomputed SHA-256
  8444b9e844f1a03c55b390d1fc66df6dc97054b756875518040ccc4784ecc218
  -- an EXACT match to the artifact reference, confirmed for the third
  time across three separate review/verification passes in this campaign
  (Pilot 5's original independent check, the full qualification pass's
  independent check, and this external-review pass's independent check),
  all three producing the identical byte count and hash.
