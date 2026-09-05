# Independent review and disposition

Two independent read-only reviewers audited C1 `75b80d2aab33929923d4d9323bcaf639bc69591b`: FinalCodeAudit covered runtime correctness; FinalEvidenceAudit covered evidence and provenance. Raw results and explicit amendments: `artifacts/independent-c1-reviews.json`.

| Finding | Disposition |
|---|---|
| P1 prompt marker could redirect ledger ancestry and parent budget lookup | Fixed in C2 `c106865d9ae620e531b64fdaaf448a1b76e160fb`. Native transcript ancestry is authoritative, not prompt text. Real CLI/SQLite smoke on isolated C1 persisted the unrelated root; C2 persisted the expected root. |
| Same first-marker issue in task-result correlation | Fixed by placing the guard-generated marker before verbatim original task text. Regression verifies the prepared packet is submitted despite a quoted fake marker. |
| P2 missing/null usage identity treated as factual usage | Fixed. C1 smoke produced HARD for malformed 400001-token records; C2 reports used:null/ACCOUNTING_UNAVAILABLE. Valid matching usage still produces HARD. |
| P2 root-linkage summary overstated integration proof | Wording narrowed. C2 additionally has a real CLI/SQLite local hook-harness smoke, but final native/provider integration remains Gate23. |
| Provisional P1 raw/sanitized alias double charge | WITHDRAWN by reviewer: no supported duplicate writer or shared invocation identity was established. Equal amounts may be separate charges; content-only dedup would undercount. |
| Same-status terminal replay returns an existing receipt despite changed transport payload | Intended immutable first-receipt semantics, not alternate-content persistence. OMP normalization generates a fresh created_at even for identical retries; strict incoming-hash equality would break replay. Returned hash identifies the original durable result. Later transport text is not merged or persisted. |
| Native unescaped task-result framing | P1 OPEN. Host framing/structured outcome contract required. |
| Populated-home governor latency | P1 qualification risk OPEN; prior paired measurements remain disclosed. |

Main reviewed the builders' changes and corrected an intermediate proposal that would have applied a child's role cap to whole-root usage. Final code preserves per-session role budgets and uses the trusted root for ancestry and parent HARD-state lookup only.

Final converged proof: Python 1825 passed; Vitest688 passed; TypeScript and changed-file ESLint pass; doctor19 checks, zero failures/warnings. Pyright85 and Ruff434 remain failing baseline-backlog gates. No provider arm, default deployment, natural twenty, or paired C2 economics is claimed. Decision remains HOLD.
