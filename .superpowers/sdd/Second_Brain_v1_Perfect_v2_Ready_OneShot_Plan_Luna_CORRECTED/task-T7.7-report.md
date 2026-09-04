# T7.7 Task Report — Universal Harness Control Plane Completion

Plan source: `C:\Users\assas\Downloads\GPTs plans\Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED.md`, lines 643–661.

## Files

- `src/second_brain/capabilities.py`
- `tests/test_universal_control_plane.py` (new)
- `scripts/generate_capability_matrix.py` (new)
- `outputs/reports/v2/control-plane/capability-matrix.json` (new)
- `outputs/reports/v2/control-plane/capability-matrix.md` (new)
- `.superpowers/sdd/Second_Brain_v1_Perfect_v2_Ready_OneShot_Plan_Luna_CORRECTED/task-T7.7-report.md` (new)

## Implemented contract

1. **No Competing Control-Plane Module**:
   Completed universal control-plane contracts using existing owners: `contracts.py`, `capabilities.py`, adapters, and `worker_protocol.py`.

2. **Universal Wire Format Roundtrip**:
   Canonical `WorkerTaskPacket` and `WorkerResultPacket` roundtrip losslessly across adapter wire formats:
   - Prime extension task dispatch wire format.
   - Claude Code lifecycle hook event payload.
   - Hermes message transport packet.
   All objectives, scopes, constraints, evidence requirements, and agent identities are preserved with identical canonical hashes.

3. **Capability Degradation & Safe Defaults**:
   Harnesses with unobserved or missing capabilities degrade to the conservative T0 floor (`injection_only`) without faking or inferring support. Declared `False` states are explicitly preserved.

4. **Capability Matrix Generation**:
   Added `capabilities.generate_capability_matrix` and generated comprehensive capability matrices for Prime, Claude Code, Codex, Antigravity, and Hermes/OMP based on verified adapter manifests and current repository observations:
   - Prime: Tier **T2** (9 supported, 1 unsupported)
   - Claude Code: Tier **T2** (7 supported, 3 unsupported)
   - Codex: Tier **T1** (4 supported, 6 unsupported)
   - Antigravity: Tier **T2** (5 supported, 5 unsupported)
   - Hermes: Tier **T2** (6 supported, 4 unsupported)

5. **Shared Canonical State**:
   Host-specific session identifiers (e.g. `claude-session-...`, `prime-uuid-...`, `hermes-agent-...`) serve as adapter transport identities only. Task registration, claims, state transitions, and settlement remain authoritative and shared in `worker_tasks` without competing state.

## Focused verification

Project venv commands run with `PYTHONHOME` and `PYTHONPATH` cleared, then `PYTHONPATH=src` set:

```text
.venv/Scripts/python.exe -m pytest tests/test_universal_control_plane.py tests/test_capabilities.py -q
15 passed

.venv/Scripts/python.exe -m pytest tests/test_worker_lifecycle.py tests/test_worker_protocol.py -q
39 passed
```

Named tests verified:
- `test_worker_packet_roundtrip_across_adapters`: PASS (lossless roundtrip across Prime, Claude Code, and Hermes wire formats)
- `test_missing_capability_degrades_not_fakes_support`: PASS (unobserved harness degrades to T0 floor without faking support)
- `test_host_identity_not_canonical_state`: PASS (host adapter session IDs do not partition canonical state in worker_tasks)

## Artifacts

Generated and saved:
- `outputs/reports/v2/control-plane/capability-matrix.json`
- `outputs/reports/v2/control-plane/capability-matrix.md`

## Migration and rollback

Additive capability matrix generator and contract verification tests; no database migration required.
Rollback is code-revert safe.

## Commit

Commit message: `brain(adapter): complete universal harness control plane`.
