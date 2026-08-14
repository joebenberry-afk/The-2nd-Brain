# Phase 9 — Episodic Memory (design)

Spec: plan §105/§46/§12. Capture only; no semantic auto-update.

## Components

1. **DB migration 0002** — `episodes` table (plan §12 fields): episode_id TEXT PK,
   project_id, session_id, task_id, episode_type, created_at, summary,
   evidence_refs (JSON list), prediction_error (0..1 REAL), salience, status,
   confidence, scope.
2. **src/second_brain/episodes.py**:
   - `create_episode(home, episode_type, summary, *, project_id=None,
     session_id=None, task_id=None, evidence_refs=None, prediction_error=None,
     salience=None, sections=None) -> episode_id`
     - id = `<type>-<YYYYmmdd>-<8hex>` (collision-checked; multi-agent-safe
       unique writes: atomic file write + transactional DB insert, retry on
       id collision)
     - writes memory/episodic/<id>.md per plan §46 template (frontmatter +
       the 14 sections; sections param fills Situation/Expected/Actual/etc.)
     - immutable: re-create with same id is refused; updates only via
       `annotate_episode` (appends a dated addendum section, never edits body)
   - `list_episodes(home, episode_type=None, project_id=None, since=None)`
   - `show_episode(home, episode_id)` — file + DB row
   - `search_episodes(home, term)` — summary/fulltext substring search
   - provenance: evidence_refs stored verbatim (commit hashes, report paths)
3. **brainctl episodes create|list|show|search** (+ create with --type, --salience,
   --evidence, --section k=v repeats).
4. **Acceptance** (plan §105): multi-agent-safe unique writes (Hypothesis:
   concurrent create sequences never collide/lose data), episode retrieval,
   provenance.

## Dogfood (v4.2 Stage 4 — real episodes only, no synthetic filler)

Candidate episodes from this build, each with evidence refs:
- E1 correction: restore WAL-replay bug (verifier-found) — commit dc0e49d,
  milestone-01 reconciliation.
- E2 correction: CRLF byte-exactness blocker in attach/detach — verifier
  FAIL -> fixed; tests test_attach_detach_preserves_crlf_exactly.
- E3 environment: PYTHONHOME pollution breaks bare python (SRE mismatch);
  shims sanitize; doctor warns. AGENTS.md gotchas.
- E4 environment: Prime print-mode daemon pins startup env — dedicated
  --daemon-socket per run needed for SECOND_BRAIN_HOME isolation.
- E5 surprise: Prime supervisor process.exit() races async extension writes —
  appendFinal sync write needed for the shutdown record.
- E6 tool-routing: print-mode flash agents decline bash for trivial
  commands; rtd_shadow live trigger needs harness-level forced tool call.
- E7 success: Scout experiment T2 — advisory promotion on 3v7 tool calls +
  bonus finding (verification.toml gate wiring).
- E8 environment: uv venvs lack pip; bootstrap must prefer `uv pip`.
- E9 correction: milestone claims "49 passed" vs actual 43 (evidence
  accuracy discipline).

Each: salience + prediction_error fields set from real experience.
