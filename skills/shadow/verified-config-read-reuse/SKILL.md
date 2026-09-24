---
name: verified-config-read-reuse
status: shadow
version: 2
project_id: second-brain
owner: Main
source_episodes:
- context-efficiency-20260908-9bab655f
created_at: 2026-09-08T15:03:35.594448+00:00
---

# Purpose

- A verified deterministic configuration-read macro plus bounded read-only students preserved all four observed settings and reduced complete paired workflow tokens from 80879 to 55772 in this controlled run.

# Positive Triggers

repeated policy configuration reads
unchanged canonical policy settings requested again

# Negative Triggers

changed configuration input hashes
policy mutation requested
missing or invalid acceptance evidence

# Inputs

- Read-only requests for the current autoinject mode, admission stage, learning stage, and retrieval token budget.
- Immutable macro `policy-config-f34927e18ed4`, version 1, content SHA-256 `72bac2e522dc185190b118e099f0667e2d7e8ab1757119b4250825403879804a`.
- Canonical `config/autoinject.toml` and `config/v2.toml`, with the current input hashes verified by the recorded macro input contract.
- Owned executor `outputs/reports/v1-v2-closure-20260908T011250Z/run-observed-config-macro.py`, SHA-256 `6a4c96ab9731344fdaac95783b2fdeb2aefc03bdd91bf6cb51ec2ff740d09ad5`.
- Input contract `outputs/reports/v1-v2-closure-20260908T011250Z/observed-config-macro-input.json`, SHA-256 `36683a34a330752afd1d3ebc1ee14f955de9b86df2c1fde66bc609b8efa11219`.

# Procedure

1. Reject mutation requests, changed input hashes, or an executor/input contract that does not match the recorded SHA-256 values. Seek fresh evidence rather than reusing stale results.
2. Execute the verified owned program with the canonical Python runtime: `brain-home/.venv/Scripts/python.exe brain-home/outputs/reports/v1-v2-closure-20260908T011250Z/run-observed-config-macro.py brain-home/outputs/reports/v1-v2-closure-20260908T011250Z/observed-config-macro-input.json`. Here `brain-home` is the resolved `SECOND_BRAIN_HOME`, not a separate checkout. The program uses the canonical engram API, actual native read tools, and TOML predicates.
3. Deliver that computed result to a read-only Scout with only the existing bounded read surface. Require the same four named output fields and verify them against the independently observed configuration.
4. Count controller and child model usage together. A zero-model deterministic macro does not make the student or complete workflow zero-token. Hold adoption when complete-workflow quality or token cost regresses.

# Tools

- Canonical Brain Python runtime and `second_brain.engram.run_deterministic`.
- The verified owned executor above, whose only native tool is `omp read` on the two approved configuration files.
- The native read-only Scout surface for consuming the validated result.

# Safety

Do not change configuration, relax worker access intent, bypass hook trust, or promote a candidate automatically. Reuse is valid only for the recorded input identity and complete acceptance contract. Keep unknown measurements null and preserve failed experiments.

# Verification

Require equality of all four returned settings, current input SHA-256 values, successful native tool outcomes, and explicit student acceptance. Compare all parent and child usage against the baseline. Re-run the canonical trigger, workflow, regression, security, and authority gates before any promotion.

# Output

Four observed settings with native session, macro version, input-hash and measured-usage provenance. This narrow workflow does not establish general savings or authorize changes to policy.

# References

- episode context-efficiency-20260908-9bab655f
- evidence outputs\reports\v1-v2-closure-20260908T011250Z\real-scout-workflow-observations.json
- evidence outputs\reports\v1-v2-closure-20260908T011250Z\bounded-student-transfer-observations.json
- evidence outputs\reports\v1-v2-closure-20260908T011250Z\real-student-workflow-observations.json
