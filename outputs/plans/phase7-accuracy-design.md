# Phase 7 — Accuracy (design)

Spec: plan §103 (risk controller, Requirement Ledger enforcement, Intent
Verifier with fresh context). HIGH-risk only at first.

## Components

1. **Risk controller** (`src/second_brain/risk.py`, deterministic):
   - Inputs: task text, repo signals (repo_path, files-to-touch list, whether
     DB/migration/security/config paths are implicated), user-criticality
     override.
   - Signals -> score (plan §35): blast radius (file count), centrality
     (DB/registry/constitution paths), concurrency (locks/processes),
     persistence (migrations/db), security boundary (constitution/immune/
     secrets paths), public API (cli.py/extension), data loss (backup/
     restore/delete), configuration scope (config/ + defaults sync).
   - Output: LOW/MEDIUM/HIGH/CRITICAL with the top contributing signals
     (explainable, no hidden scores). `brainctl risk assess <session-id>`
     reads the capsule + repo, prints verdict + signals.
2. **Requirement Ledger enforcement**: already live (Phase 4 gate); Phase 7
   adds risk-aware defaults: HIGH/CRITICAL tasks fail `requirements check`
   unless every material requirement is verified; LOW/MEDIUM require at least
   one evidence entry per material requirement (partial gate). Constant in
   verification.toml `[requirement_ledger]` (thresholds per risk).
3. **Intent Verifier** (`src/second_brain/verify.py`): builds a verifier brief
   from the session working set: original requirements (ledger), constraints
   (capsule), diff (git diff of touched files), validation evidence
   (requirement evidence entries) — explicitly WITHOUT solver reasoning.
   `brainctl verify-task <session-id> [--model deepseek/deepseek-v4-pro]`
   renders the brief to outputs/verification/<session-id>.md and prints the
   spawn command for a fresh-context agent. The retained reviewer child is the
   canonical executor (reuse policy). Backward reconstruction (plan §38): the
   brief instructs the verifier to infer intent from the diff BEFORE reading
   the requirements section.
4. **Eval for acceptance** (plan §103): a planted requirement/test mismatch
   scenario (checked-in eval fixture): a task + patch where tests satisfy a
   narrow oracle but a requirement is unimplemented; the verifier must flag
   it; plus one low-risk task showing no false blocking.

## Delegation

risk.py + verify.py + tests -> reused worker (repowise-recon or
phase2-ts-worker, whoever is free first); parent wires CLI + runs the eval +
writes milestone-07.
