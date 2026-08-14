# Build Decisions (global) — 2026-08-14

| # | Decision | Rationale | Status |
|---|---|---|---|
| 1 | v4.1 OneShot plan is authoritative; v4 Definitive kept as history | plan supersedes | accepted |
| 2 | Stdlib-only Python; dev-only deps (pytest/ruff/pyright/hypothesis) | plan §5 policy | accepted |
| 3 | Hand-written ambient TS types for Prime extension (local v0.7.2 unpublished on npm) | runtime drift guarded by real integration test | accepted (deviation) |
| 4 | RepoWise: detection now, index init deferred to Phase 6 (Scout) | no usable index exists; avoid unused derived artifact | accepted (deviation) |
| 5 | Material requirements = importance critical/high unverified | plan §18 leaves "material" underspecified | accepted |
| 6 | Generic [tools] manifest omits sz_tool (SZ-specific) | projects add it themselves | accepted (deviation) |
| 7 | Detach deletes an AGENTS.md that was only our marker | empty file carries no user content | accepted (deviation) |
| 8 | User policy: reuse idle RLM children; never spawn new ones while a reusable child exists | user instruction (persisted globally) | accepted |
| 9 | Completion-reserve: memory retrieval must never consume task-critical context; measure retrieved tokens separately once memory exists | goal doctrine | accepted |
| 10 | Self-hosting evidence is supplementary; acceptance needs independent tests/tooling/verification | no circular proof | accepted |
