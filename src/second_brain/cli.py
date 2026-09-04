"""brainctl — Python control CLI (plan §82).

Implemented in Phase 1: init, doctor, status, project add|list|status,
backup, restore. Later phases add capture/recall/sleep/skills/... commands.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import cast

from . import (
    __version__,
    antigravity_transcript,
    artifacts,
    capabilities,
    capsule_runtime,
    cerebellum,
    contracts,
    credit,
    crossmodel,
    db,
    decisions,
    economics,
    engram,
    envsteward,
    episodes,
    frontier,
    governor,
    handoff,
    immune,
    ledger,
    monitor,
    optimization,
    paths,
    plasticity,
    promotion,
    radar,
    reconsolidation,
    registry,
    risk,
    router,
    scout,
    semantic,
    simplification,
    skillforge,
    sleep,
    verify,
    working_set,
)
from . import backup as backup_mod
from . import doctor as doctor_mod
from . import jit as jit_mod
from .errors import BrainError


def _parser() -> argparse.ArgumentParser:
    # --home is accepted both before and after the subcommand. SUPPRESS keeps
    # the subparser default from clobbering a value given at the root level.
    home_parent = argparse.ArgumentParser(add_help=False)
    home_parent.add_argument(
        "--home",
        type=Path,
        default=argparse.SUPPRESS,
        help="Brain root (default: $SECOND_BRAIN_HOME)",
    )
    p = argparse.ArgumentParser(
        prog="brainctl", description="The Second Brain control CLI", parents=[home_parent]
    )
    p.add_argument("--version", action="version", version=f"brainctl {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[home_parent], help="initialize a Brain at the root")
    init.add_argument(
        "--force", action="store_true", help="initialize even if the directory is non-empty"
    )
    doctor_parser = sub.add_parser("doctor", parents=[home_parent], help="run health checks")
    doctor_parser.add_argument("--repo", type=Path, default=None)
    doctor_parser.add_argument("--session", dest="session_id", default=None)
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--out", type=Path, default=None)
    sub.add_parser("status", parents=[home_parent], help="show Brain status summary")

    pa = sub.add_parser("project", parents=[home_parent], help="project registry")
    ps = pa.add_subparsers(dest="project_command", required=True)
    padd = ps.add_parser(
        "add",
        parents=[home_parent],
        help="attach a repository (registry + manifest + marker)",
    )
    padd.add_argument("repo", type=Path)
    padd.add_argument("--name", default=None)
    padd.add_argument("--id", dest="project_id", default=None)
    padd.add_argument("--no-marker", action="store_true", help="skip the AGENTS.md marker block")
    padd.add_argument("--no-manifest", action="store_true", help="skip .brain/project.toml")
    plist = ps.add_parser("list", parents=[home_parent], help="list registered projects")
    plist.add_argument("--inactive", action="store_true")
    pstat = ps.add_parser("status", parents=[home_parent], help="status of one registered project")
    pstat.add_argument("key")
    pdet = ps.add_parser(
        "detach",
        parents=[home_parent],
        help="remove repo-side integration (marker/manifest) and deactivate",
    )
    pdet.add_argument("key")
    prem = ps.add_parser(
        "remove",
        parents=[home_parent],
        help="delete a registry row (keep brain dir unless --purge)",
    )
    prem.add_argument("key")
    prem.add_argument("--purge", action="store_true", help="also delete projects/<id>/")

    b = sub.add_parser("backup", parents=[home_parent], help="create a Brain backup")
    b.add_argument("--note", default=None)
    r = sub.add_parser("restore", parents=[home_parent], help="restore a Brain backup")
    r.add_argument("backup_dir", type=Path)
    r.add_argument("--force", action="store_true")

    cap = sub.add_parser("capsule", parents=[home_parent], help="Active State Capsule (Phase 4)")
    cps = cap.add_subparsers(dest="capsule_command", required=True)
    censure = cps.add_parser("ensure", parents=[home_parent], help="create or bind a capsule")
    censure.add_argument("session_id")
    censure.add_argument("objective")
    censure.add_argument("--next-action", default=None)
    censure.add_argument("--task-mode", default="STANDARD")
    censure.add_argument("--risk", default="MEDIUM")
    censure.add_argument("--json", action="store_true")
    cinit = cps.add_parser("init", parents=[home_parent], help="create a capsule")
    cinit.add_argument("session_id")
    cinit.add_argument("objective")
    cinit.add_argument("--task-mode", default="STANDARD")
    cinit.add_argument("--risk", default="MEDIUM")
    cinit.add_argument("--constraint", action="append", default=None)
    cupd = cps.add_parser("update", parents=[home_parent], help="update a capsule")
    cupd.add_argument("session_id")
    cupd.add_argument("--objective", default=None)
    cupd.add_argument("--next-action", default=None)
    cupd.add_argument("--task-mode", default=None)
    cupd.add_argument("--risk", default=None)
    cupd.add_argument("--json", action="store_true")
    cupd.add_argument("--verification-json", default=None)
    for name, dest in (
        ("--add-constraint", "constraints"),
        ("--add-fact", "confirmed_facts"),
        ("--add-hypothesis", "current_hypotheses"),
        ("--add-decision", "decisions_this_session"),
        ("--add-file", "files_touched"),
        ("--add-question", "open_questions"),
        ("--add-brain-ref", "brain_refs"),
        ("--add-artifact-ref", "artifact_refs"),
    ):
        cupd.add_argument(name, dest=dest, action="append", default=None)
    cshow = cps.add_parser("show", parents=[home_parent], help="show a capsule")
    cshow.add_argument("session_id")

    req = sub.add_parser("requirements", parents=[home_parent], help="Requirement Ledger (Phase 4)")
    rs = req.add_subparsers(dest="requirements_command", required=True)
    radd = rs.add_parser("add", parents=[home_parent], help="add a requirement")
    radd.add_argument("session_id")
    radd.add_argument("requirement")
    radd.add_argument("--id", dest="req_id", default=None)
    radd.add_argument("--importance", default="normal")
    rev = rs.add_parser("evidence", parents=[home_parent], help="attach evidence to a requirement")
    rev.add_argument("session_id")
    rev.add_argument("req_id")
    rev.add_argument("evidence")
    rst = rs.add_parser("status", parents=[home_parent], help="set a requirement status")
    rst.add_argument("session_id")
    rst.add_argument("req_id")
    rst.add_argument("status")
    rsh = rs.add_parser("show", parents=[home_parent], help="list requirements")
    rsh.add_argument("session_id")
    rs.add_parser(
        "check", parents=[home_parent], help="fail if material requirements are unverified"
    ).add_argument("session_id")
    ho = sub.add_parser(
        "handoff",
        parents=[home_parent],
        help="Brain Handoff Envelope: bounded cross-harness transfer (P3.17)",
    )
    hos = ho.add_subparsers(dest="handoff_command", required=True)
    hcreate = hos.add_parser(
        "create", parents=[home_parent], help="create a canonical bounded handoff envelope"
    )
    hcreate.add_argument("session_id")
    hcreate.add_argument("--source-harness", required=True)
    hcreate.add_argument("--target-harness", default="")
    hcreate.add_argument("--target-role", default="")
    hcreate.add_argument("--source-task-id", default="")
    hcreate.add_argument("--source-role", default="")
    hcreate.add_argument("--project", dest="project_id", default="")
    hcreate.add_argument("--context-ref", dest="context_refs", action="append", default=None)
    hcreate.add_argument("--artifact-ref", dest="artifact_refs", action="append", default=None)
    hcreate.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=None)
    hcreate.add_argument(
        "--unavailable-evidence", dest="unavailable_evidence", action="append", default=None
    )
    hcreate.add_argument("--json", action="store_true")
    hread = hos.add_parser(
        "read", parents=[home_parent], help="validate + losslessly recover a handoff envelope"
    )
    hread.add_argument("envelope_path", type=Path)
    hread.add_argument("--project", dest="project_id", default=None)
    hread.add_argument("--allow-stale", action="store_true")
    simp = sub.add_parser(
        "simplification",
        parents=[home_parent],
        help="Simplification Review (P3.5)",
    )
    simps = simp.add_subparsers(dest="simplification_command", required=True)
    srev = simps.add_parser("review", parents=[home_parent], help="record one bounded review")
    srev.add_argument("--project-root", type=Path, required=True)
    srev.add_argument("--project", dest="project_id", required=True)
    srev.add_argument("--session", dest="session_id", required=True)
    srev.add_argument("--task-id", required=True)
    srev.add_argument("--review-id", required=True)
    srev.add_argument(
        "--outcome",
        choices=[item.value for item in simplification.SimplificationOutcome],
        required=True,
    )
    srev.add_argument("--reason-code", required=True)
    srev.add_argument("--affected-hash", action="append", default=[])
    srev.add_argument("--changed-hash", action="append", default=[])
    srev.add_argument("--deferred-hash", action="append", default=[])
    srev.add_argument("--debt-ref", default=None)
    srev.add_argument(
        "--verification",
        choices=["passed", "failed", "blocked", "not_run"],
        default="passed",
    )
    srev.add_argument("--metric", action="append", default=[], help="key=value metric")
    srev.add_argument("--json", action="store_true")

    rl = sub.add_parser("read-ledger", parents=[home_parent], help="Read Ledger (Phase 4)")
    rls = rl.add_subparsers(dest="read_ledger_command", required=True)
    rrec = rls.add_parser("record", parents=[home_parent], help="record a file read")
    rrec.add_argument("session_id")
    rrec.add_argument("path")
    rrec.add_argument("--purpose", default="")
    rrec.add_argument("--turn", type=int, default=None)
    rrec.add_argument("--range", dest="range_text", default=None)
    rrec.add_argument("--artifact", default=None)
    rrec.add_argument("--distilled-ref", default=None)
    rlshow = rls.add_parser("show", parents=[home_parent], help="show the read ledger")
    rlshow.add_argument("session_id")

    wset = sub.add_parser("working-set", parents=[home_parent], help="Working-set read hints")
    wsets = wset.add_subparsers(dest="working_set_command", required=True)
    rhint = wsets.add_parser("reread-hint", parents=[home_parent], help="check whether a file is unchanged")
    rhint.add_argument("session_id")
    rhint.add_argument("path")
    rhint.add_argument("--mode", choices=("OFF", "SHADOW", "ACTIVE"), default="SHADOW")
    rhint.add_argument("--tool", default="read")
    rhint.add_argument("--tool-call-id", default=None)

    cc = sub.add_parser("context", parents=[home_parent], help="JIT Context Compiler (Phase 4)")
    ccs = cc.add_subparsers(dest="context_command", required=True)
    ccomp = ccs.add_parser("compile", parents=[home_parent], help="compile a Task Context Capsule")
    ccomp.add_argument("session_id")
    ccomp.add_argument("task")
    ccomp.add_argument("--project", dest="project_key", default=None)

    ai = sub.add_parser(
        "autoinject", parents=[home_parent], help="P0 AutoInject pipeline (SHADOW, Phase 0C)"
    )
    ais = ai.add_subparsers(dest="autoinject_command", required=True)
    ashadow = ais.add_parser(
        "shadow",
        parents=[home_parent],
        help="shadow run: decide + record, never mutate model context",
    )
    ashadow.add_argument("--task", required=True, help="task text (queried, never persisted)")
    ashadow.add_argument(
        "--project",
        dest="project_id",
        default=None,
        help="project id (default: registry root containing --cwd > env > 'default')",
    )
    ashadow.add_argument(
        "--cwd", default=None, help="working directory for project resolution"
    )
    ashadow.add_argument("--session", dest="session_id", required=True, help="host session id")
    ashadow.add_argument("--agent", dest="agent_id", required=True, help="host agent id")
    ashadow.add_argument("--branch", default="main", help="branch/lineage id (default: main)")
    ashadow.add_argument("--role", dest="role_profile", default="orchestrator", help="role profile")
    ashadow.add_argument("--json", action="store_true", help="print one deterministic JSON object")

    ais.add_parser(
        "codex-shadow",
        parents=[home_parent],
        help="Codex hook adapter: one JSON object on stdin, one on stdout (SHADOW)",
    )
    ais.add_parser(
        "antigravity-hook",
        parents=[home_parent],
        help="Antigravity hook adapter: lifecycle JSON on stdin -> JSON on stdout",
    )
    ais.add_parser(
        "claude-code-hook",
        parents=[home_parent],
        help="Claude Code hook adapter: SessionStart/PreCompact/Stop JSON on stdin -> stdout",
    )
    ais.add_parser(
        "hermes-hook",
        parents=[home_parent],
        help="Hermes plugin adapter: lifecycle JSON on stdin -> stdout",
    )
    ais.add_parser(
        "omp-routing",
        parents=[home_parent],
        help="OMP model-routing adapter: bounded JSON on stdin -> JSON on stdout",
    )
    awb = ais.add_parser(
        "writeback", parents=[home_parent], help="P0-G9 write-back: create an outcome candidate"
    )
    awb.add_argument("--session", dest="session_id", required=True)
    awb.add_argument("--project", dest="project_id", required=True)
    awb.add_argument("--title", required=True)
    awb.add_argument("--observation", required=True)
    awb.add_argument("--guidance", default="")
    awb.add_argument(
        "--evidence",
        default="[]",
        help='JSON list of {"ref","kind"} source refs (default: [])',
    )

    orch = sub.add_parser(
        "orchestration",
        parents=[home_parent],
        help="P1 orchestration telemetry (Phase D; amendment §12/§22)",
    )
    ors = orch.add_subparsers(dest="orchestration_command", required=True)
    orec = ors.add_parser(
        "record",
        parents=[home_parent],
        help="record one orchestration counters event from JSON stdin; computes delegation_purity",
    )
    orec.add_argument("--session", default=None, help="session id for the telemetry file name")

    stop = sub.add_parser(
        "stop", parents=[home_parent], help="P3.6 bounded STOP decision and evidence"
    )
    stops = stop.add_subparsers(dest="stop_command", required=True)
    sdecide = stops.add_parser("decide", parents=[home_parent], help="evaluate and record STOP")
    sdecide.add_argument("--session", dest="host_session_id", required=True)
    sdecide.add_argument("--task-id", required=True)
    sdecide.add_argument("--parent-session-id", default="")
    sdecide.add_argument("--worker-session-id", default="")
    sdecide.add_argument("--stop-id", required=True)
    sdecide.add_argument("--reason-code", required=True)
    sdecide.add_argument("--triggering-condition", required=True)
    sdecide.add_argument(
        "--verification-state",
        choices=("passed", "failed", "blocked", "unverified"),
        required=True,
    )
    sdecide.add_argument(
        "--completion-condition-state",
        choices=("satisfied", "failed", "blocked", "unresolved"),
        required=True,
    )
    sdecide.add_argument("--final-substantive-event", required=True)
    sdecide.add_argument("--gate-file", type=Path, default=None)
    sdecide.add_argument("--json", action="store_true")

    led = sub.add_parser(
        "ledger", parents=[home_parent], help="P2 session ledger (plan §9/§9.10; Phase G)"
    )
    leds = led.add_subparsers(dest="ledger_command", required=True)
    lin = leds.add_parser("init", parents=[home_parent], help="initialize a session ledger")
    lin.add_argument("--session", dest="host_session_id", required=True, help="HOST session id")
    lin.add_argument("--project", dest="project_id", default=None)
    lin.add_argument(
        "--cwd",
        default=None,
        help="working directory for project resolution "
        "(reuses the AutoInject ladder: explicit --project > registry root "
        "containing cwd > SECOND_BRAIN_PROJECT env > 'default')",
    )
    lin.add_argument("--host", default="prime")
    lin.add_argument(
        "--host-artifact",
        dest="host_artifacts",
        action="append",
        default=[],
        metavar="KIND=PATH",
        help="reference a Prime-owned artifact (repeatable; never copied into the ledger)",
    )
    lapp = leds.add_parser("append", parents=[home_parent], help="append events from JSON stdin")
    lapp.add_argument("--session", dest="host_session_id", required=True)
    lapp.add_argument(
        "--stdin-json",
        action="store_true",
        help="read ONE event object or an array from stdin",
    )
    lver = leds.add_parser("verify", parents=[home_parent], help="fresh replay + integrity")
    lver.add_argument("host_session_id")
    lver.add_argument("--lineage", default=None, help="comma-separated event ids root->leaf")
    lre = leds.add_parser("reindex", parents=[home_parent], help="rebuild the events FTS index")
    lre.add_argument("host_session_id")
    lse = leds.add_parser("search", parents=[home_parent], help="FTS search over events")
    lse.add_argument("host_session_id")
    lse.add_argument("--query", required=True)
    lse.add_argument("--segment", default=None)
    lse.add_argument("--agent", default=None)
    lse.add_argument("--event-type", dest="event_type", default=None)
    lseg = leds.add_parser("segment", parents=[home_parent], help="segment lifecycle (plan §10.3)")
    lsegs = lseg.add_subparsers(dest="segment_command", required=True)
    sopen = lsegs.add_parser(
        "open", parents=[home_parent], help="close prior active segment, open a new one"
    )
    sopen.add_argument("host_session_id")
    sopen.add_argument("--reason", default="manual")
    sclose = lsegs.add_parser("close", parents=[home_parent], help="close the active segment")
    sclose.add_argument("host_session_id")
    schk = lsegs.add_parser(
        "checkpoint",
        parents=[home_parent],
        help="pre-compaction durability barrier (flush + integrity)",
    )
    schk.add_argument("host_session_id")
    lrh = leds.add_parser("rehydrate", parents=[home_parent], help="rehydration levels 1-4 (§17.5)")
    lrh.add_argument("host_session_id")
    lrh.add_argument("--level", type=int, required=True, choices=[1, 2, 3, 4])
    lrh.add_argument("--segment", default=None)
    lrh.add_argument("--decision", default=None)
    lrh.add_argument("--from-seq", dest="from_seq", type=int, default=None)
    lrh.add_argument("--to-seq", dest="to_seq", type=int, default=None)

    ses = sub.add_parser(
        "session",
        parents=[home_parent],
        help="P2 session lifecycle: recovery, retention, purge (plan §12/§13)",
    )
    sess = ses.add_subparsers(dest="session_command", required=True)
    slist = sess.add_parser(
        "list", parents=[home_parent], help="list session ledgers + purge receipts"
    )
    slist.add_argument("--json", action="store_true")
    spin = sess.add_parser(
        "pin", parents=[home_parent], help="pin a session (preserve from auto-purge)"
    )
    spin.add_argument("host_session_id")
    spin.add_argument("--unpin", action="store_true")
    spurg = sess.add_parser("purge", parents=[home_parent], help="finalize+purge a session ledger")
    spurg.add_argument("host_session_id", nargs="?", default=None)
    spurg.add_argument(
        "--inactive", action="store_true", help="allow purging an inactive_grace session"
    )
    spurg.add_argument("--dry-run", action="store_true")
    spurg.add_argument(
        "--oldest",
        action="store_true",
        help="choose the oldest inactive unpinned session (storage pressure)",
    )
    srec = sess.add_parser("recover", parents=[home_parent], help="crash recovery report")
    srec.add_argument("host_session_id")


    art = sub.add_parser(
        "artifact", parents=[home_parent], help="Reversible Tool Distillation store (Phase 5)"
    )
    ars = art.add_subparsers(dest="artifact_command", required=True)
    astore = ars.add_parser(
        "store", parents=[home_parent], help="store a file or stdin as an artifact"
    )
    astore.add_argument("path", nargs="?", default=None, help="file to store (default: stdin)")
    astore.add_argument("--kind", default="generic")
    astore.add_argument("--tool", default="")
    astore.add_argument("--session", default=None)
    astore.add_argument("--no-distill", action="store_true", help="skip distilled preview")
    aexp = ars.add_parser(
        "expand", parents=[home_parent], help="recover a stored artifact byte-identically"
    )
    aexp.add_argument("hash_prefix")
    ars.add_parser("list", parents=[home_parent], help="list stored artifacts")

    sc = sub.add_parser("scout", parents=[home_parent], help="isolated repo explorer (Phase 6)")
    scs = sc.add_subparsers(dest="scout_command", required=True)
    srun = scs.add_parser(
        "run", parents=[home_parent], help="run an isolated exploration -> Evidence Map"
    )
    srun.add_argument("target", help="repo path or registered project key")
    srun.add_argument("--task", required=True, help="exploration objective")
    srun.add_argument("--model", default="deepseek/deepseek-v4-flash")
    srun.add_argument("--no-agent", action="store_true", help="pre-pass only (no agent run)")
    srun.add_argument("--ext", default=None, help="prime extension path to load (-e)")
    srun.add_argument(
        "--output", default=None, help="evidence maps dir (default outputs/evidence-maps)"
    )

    rk = sub.add_parser("risk", parents=[home_parent], help="risk controller (Phase 7)")
    rks = rk.add_subparsers(dest="risk_command", required=True)
    rassess = rks.add_parser("assess", parents=[home_parent], help="assess task risk")
    rassess.add_argument("repo", type=Path)
    rassess.add_argument("--file", dest="files", action="append", default=[])
    rassess.add_argument("--criticality", default=None, choices=risk.RISK_LEVELS)
    rassess.add_argument(
        "--verification-ladder",
        action="store_true",
        help="append the compact risk-adaptive verification ladder for the "
        "resulting risk level (plan §10; config/verification.toml [ladder])",
    )

    radar_parser = sub.add_parser(
        "radar", parents=[home_parent], help="improvement radar (P3.10)"
    )
    radar_sub = radar_parser.add_subparsers(dest="radar_command", required=True)
    robs = radar_sub.add_parser(
        "observe", parents=[home_parent], help="observe one telemetry session"
    )
    robs.add_argument("session_id")
    robs.add_argument("--project-id", required=True)
    robs.add_argument("--repo", type=Path, required=True)
    robs.add_argument("--task-id", default=None)
    robs.add_argument("--out", type=Path, default=None)
    robs.add_argument("--json", action="store_true")
    rval = radar_sub.add_parser(
        "validate", parents=[home_parent], help="validate candidate telemetry evidence"
    )
    rval.add_argument("candidate_id")
    rval.add_argument("--json", action="store_true")

    vf = sub.add_parser("verify", parents=[home_parent], help="intent verifier brief (Phase 7)")
    vfs = vf.add_subparsers(dest="verify_command", required=True)
    vbuild = vfs.add_parser(
        "build-brief", parents=[home_parent], help="build a fresh-context verifier brief"
    )
    vbuild.add_argument("session_id")
    vbuild.add_argument("repo", type=Path)
    vgate = vfs.add_parser(
        "gate", parents=[home_parent], help="evaluate the risk-adaptive completion gate"
    )
    vgate.add_argument("session_id")
    vgate.add_argument("repo", type=Path)
    vgate.add_argument("--file", dest="files", action="append", default=[])
    vgate.add_argument("--criticality", choices=risk.RISK_LEVELS, default=None)
    vgate.add_argument("--action", action="append", default=[], metavar="ACTION=STATE")
    vgate.add_argument(
        "--approval-state",
        choices=("not_required", "required", "approved"),
        default="not_required",
    )
    vgate.add_argument("--task-id", default="")
    vgate.add_argument("--parent-session-id", default="")
    vgate.add_argument("--worker-session-id", default="")
    vgate.add_argument("--verification-file", type=Path, default=None)
    vgate.add_argument("--task-hash", default="")
    vgate.add_argument("--requirements-hash", default="")
    vgate.add_argument("--diff-hash", default="")
    vgate.add_argument("--evidence-set-hash", default="")
    vgate.add_argument("--environment-file", type=Path, default=None)
    vgate.add_argument("--environment-required", action="store_true")
    vgate.add_argument("--out", type=Path, default=None)
    vgate.add_argument("--json", action="store_true")
    vind = vfs.add_parser(
        "independent",
        parents=[home_parent],
        help="record one bounded fresh verifier verdict",
    )
    vind.add_argument("--task-file", type=Path, default=None)
    vind.add_argument("--requirements-file", type=Path, default=None)
    vind.add_argument("--diff-file", type=Path, default=None)
    vind.add_argument("--evidence-file", type=Path, default=None)
    vind.add_argument("--response-file", type=Path, required=True)
    vind.add_argument("--verification-id", required=True)
    vind.add_argument("--task-id", required=True)
    vind.add_argument("--verifier-session-id", required=True)
    vind.add_argument("--implementation-session-id", required=True)
    vind.add_argument("--task-hash", required=True)
    vind.add_argument("--requirements-hash", required=True)
    vind.add_argument("--diff-hash", required=True)
    vind.add_argument("--evidence-set-hash", required=True)
    vind.add_argument("--failed-requirement-id", action="append", default=[])
    vind.add_argument("--unresolved-requirement-id", action="append", default=[])
    vind.add_argument("--out", type=Path, required=True)
    vind.add_argument("--json", action="store_true")


    envp = sub.add_parser("env", parents=[home_parent], help="environment steward (Phase 8)")
    eps = envp.add_subparsers(dest="env_command", required=True)
    esnap = eps.add_parser(
        "snapshot", parents=[home_parent], help="capture an environment snapshot"
    )
    esnap.add_argument("repo", type=Path)
    esnap.add_argument("--session", dest="session_id", default=None)
    esnap.add_argument("--json", action="store_true", dest="as_json")
    eassess = eps.add_parser(
        "assess", parents=[home_parent], help="capture bounded Environment Steward evidence"
    )
    eassess.add_argument("repo", type=Path)
    eassess.add_argument("--session", dest="session_id", required=True)
    eassess.add_argument("--task-id", default=None)
    eassess.add_argument(
        "--phase",
        choices=("session_start", "task_boundary", "mutation", "doctor", "shutdown"),
        default="session_start",
    )
    eassess.add_argument("--expected-field", action="append", default=[])
    eassess.add_argument("--requested-change", action="append", default=[])
    eassess.add_argument(
        "--mutation-state", choices=("observed", "failed", "partial"), default="observed"
    )
    eassess.add_argument("--json", action="store_true", dest="as_json")
    eassess.add_argument("--out", type=Path, default=None)

    pr = sub.add_parser("processes", parents=[home_parent], help="process ownership (Phase 8)")
    prs = pr.add_subparsers(dest="processes_command", required=True)
    preg = prs.add_parser("register", parents=[home_parent], help="register an owned process")
    preg.add_argument("pid", type=int)
    preg.add_argument("exe")
    preg.add_argument("--token", default="second-brain")
    preg.add_argument("--session", dest="session_id", default=None)
    prs.add_parser("list", parents=[home_parent], help="list registered processes")
    pver = prs.add_parser("verify", parents=[home_parent], help="verify a live process identity")
    pver.add_argument("pid", type=int)
    pver.add_argument("exe")
    pcl = prs.add_parser("cleanup", parents=[home_parent], help="clean up owned processes")
    pcl.add_argument("--kill", action="store_true", help="actually kill (default: dry run)")

    ep = sub.add_parser("episodes", parents=[home_parent], help="episodic memory (Phase 9)")
    eps9 = ep.add_subparsers(dest="episodes_command", required=True)
    ec = eps9.add_parser("create", parents=[home_parent], help="capture an episode")
    ec.add_argument("episode_type", choices=episodes.EPISODE_TYPES)
    ec.add_argument("summary")
    ec.add_argument("--project", dest="project_id", default="second-brain")
    ec.add_argument("--session", dest="session_id", default=None)
    ec.add_argument("--task", dest="task_id", default=None)
    ec.add_argument("--evidence", dest="evidence_refs", action="append", default=None)
    ec.add_argument("--prediction-error", type=float, default=None)
    ec.add_argument("--salience", type=float, default=None)
    ec.add_argument("--confidence", default=None)
    ec.add_argument(
        "--section",
        dest="sections",
        action="append",
        default=None,
        help="k=v section content (repeatable)",
    )
    el = eps9.add_parser("list", parents=[home_parent], help="list episodes")
    el.add_argument("--type", dest="episode_type", default=None)
    el.add_argument("--project", dest="project_id", default=None)
    el.add_argument("--since", default=None)
    es = eps9.add_parser("show", parents=[home_parent], help="show one episode")
    es.add_argument("episode_id")
    eq = eps9.add_parser("search", parents=[home_parent], help="search episodes")
    eq.add_argument("term")
    eq.add_argument("--limit", type=int, default=20)
    ea = eps9.add_parser("annotate", parents=[home_parent], help="append an addendum")
    ea.add_argument("episode_id")
    ea.add_argument("note")

    remember_parser = sub.add_parser(
        "remember", parents=[home_parent], help="remember one evidence-backed claim"
    )
    remember_parser.add_argument("claim")
    remember_parser.add_argument(
        "--evidence",
        action="append",
        default=None,
        help="capture local git evidence path[:start-end] (repeatable)",
    )
    remember_parser.add_argument(
        "--grade", choices=("OBSERVED", "TESTED", "VERIFIED"), default="OBSERVED"
    )
    recall_parser = sub.add_parser("recall", parents=[home_parent], help="recall relevant memories")
    recall_parser.add_argument("question")

    mm = sub.add_parser("memory", parents=[home_parent], help="semantic memory (Phase 10)")
    mms = mm.add_subparsers(dest="memory_command", required=True)
    madd = mms.add_parser("add", parents=[home_parent], help="add a semantic memory (candidate)")
    madd.add_argument("title")
    madd.add_argument("body")
    madd.add_argument("--scope", default="project", choices=semantic.SCOPES)
    # P3-cleanup (pre-P3 truth): NO silent second-brain default. A
    # project-scoped write must resolve from explicit --project or the
    # registered-project root containing the working directory, or fail
    # clearly (see cmd_memory). Global/domain scopes are unaffected.
    madd.add_argument("--project", dest="project_id", default=None)
    madd.add_argument("--grade", default="OBSERVED", choices=semantic.GRADES)
    madd.add_argument("--source", dest="sources", action="append", default=None)
    madd.add_argument(
        "--evidence",
        action="append",
        default=None,
        help="capture local git evidence path[:start-end] (repeatable)",
    )
    mcur = mms.add_parser(
        "curate", parents=[home_parent], help="curate: set grade/status with rules"
    )
    mcur.add_argument("memory_id")
    mcur.add_argument("--grade", default=None, choices=semantic.GRADES)
    mcur.add_argument("--status", default=None, choices=semantic.STATUSES)
    mcur.add_argument(
        "--authority-ceiling", dest="authority_ceiling", default=None,
        choices=semantic.AUTHORITY_CEILINGS,
    )
    mcur.add_argument("--source", dest="sources", action="append", default=None)
    mcur.add_argument("--no-verify", action="store_true")
    mlist = mms.add_parser("list", parents=[home_parent], help="list memories")
    mlist.add_argument("--scope", default=None)
    mlist.add_argument("--project", dest="project_id", default=None)
    mlist.add_argument("--status", default=None)
    mlist.add_argument("--grade", default=None)
    mshow = mms.add_parser("show", parents=[home_parent], help="show one memory")
    mshow.add_argument("memory_id")
    msup = mms.add_parser(
        "supersede", parents=[home_parent], help="supersede with a new version (history preserved)"
    )
    msup.add_argument("memory_id")
    msup.add_argument("new_body")
    msup.add_argument("--title", dest="new_title", default=None)
    msup.add_argument("--note", dest="change_note", default="superseded")
    msup.add_argument("--source", dest="new_sources", action="append", default=None)
    mhis = mms.add_parser("history", parents=[home_parent], help="version history of a memory")
    mhis.add_argument("memory_id")
    mcon = mms.add_parser(
        "contradictions", parents=[home_parent], help="list contradiction candidates"
    )
    mcon.add_argument("--scope", default="project")
    msearch = mms.add_parser(
        "search", parents=[home_parent], help="search memories (Phase 7 filters on by default)"
    )
    msearch.add_argument("term")
    msearch.add_argument(
        "--project", dest="project_id", default=None, help="restrict to one project"
    )
    msearch.add_argument(
        "--history", action="store_true", help="re-include archived/superseded memories"
    )
    msearch.add_argument(
        "--duplicates", action="store_true", help="return all near-duplicate versions (comparison)"
    )
    mms.add_parser(
        "reindex", parents=[home_parent], help="rebuild the derived SQLite/FTS5 memory index"
    )

    mc = sub.add_parser(
        "metacog", parents=[home_parent], help="metacognitive monitor (Phase 11, shadow)"
    )
    mcs = mc.add_subparsers(dest="metacog_command", required=True)
    mca = mcs.add_parser("assess", parents=[home_parent], help="assess trajectory confidence")
    mca.add_argument("session_id", help="working-set session id to read")
    mca.add_argument("--telemetry", default=None, help="path to a telemetry JSONL file")
    mca.add_argument("--repo", default=None, help="repo path for git info")
    mce = mcs.add_parser("eval", parents=[home_parent], help="run the labeled-trajectory eval")
    mce.add_argument(
        "--fixture",
        default=None,
        help="trajectories.json path (default: tests/fixtures/trajectories.json)",
    )

    cb = sub.add_parser(
        "cerebellum", parents=[home_parent], help="predictive workflow (Phase 12, advisory)"
    )
    cbs = cb.add_subparsers(dest="cerebellum_command", required=True)
    cba = cbs.add_parser("assess", parents=[home_parent], help="assess workflow progress")
    cba.add_argument("session_id")
    cbs.add_parser("eval", parents=[home_parent], help="run the labeled-workflow eval")

    pl = sub.add_parser(
        "plasticity", parents=[home_parent], help="plasticity records (Phase 13, shadow)"
    )
    pls = pl.add_subparsers(dest="plasticity_command", required=True)
    pp = pls.add_parser("predict", parents=[home_parent], help="record a prediction event")
    pp.add_argument("session_id")
    pp.add_argument("state")
    pp.add_argument("expected")
    pp.add_argument("actual")
    pp.add_argument("kind")
    po = pls.add_parser("outcome", parents=[home_parent], help="record an outcome vector")
    po.add_argument("session_id")
    po.add_argument("--key", dest="kv", action="append", default=[], help="k=v (repeatable)")
    pc = pls.add_parser(
        "credit", parents=[home_parent], help="record a credit event (explicit level)"
    )
    pc.add_argument("session_id")
    pc.add_argument("subject_id")
    pc.add_argument(
        "--kind",
        dest="subject_kind",
        required=True,
        choices=("skill", "memory", "policy", "tool", "scout", "verification"),
    )
    pc.add_argument(
        "--level",
        dest="credit_level",
        required=True,
        choices=("direct", "contributory", "correlated", "unknown"),
    )
    ph = pls.add_parser("hindsight", parents=[home_parent], help="record a bottleneck relabel")
    ph.add_argument("session_id")
    ph.add_argument("predicted")
    ph.add_argument("actual")
    pu = pls.add_parser("utility", parents=[home_parent], help="append a utility delta (shadow)")
    pu.add_argument("subject_id")
    pu.add_argument(
        "--kind",
        dest="subject_kind",
        required=True,
        choices=("skill", "memory", "policy", "tool", "scout", "verification"),
    )
    pu.add_argument("--delta", type=float, required=True)
    pu.add_argument("--evidence", default="")

    sl = sub.add_parser("sleep", parents=[home_parent], help="replay / sleep (Phase 14, manual)")
    sls = sl.add_subparsers(dest="sleep_command", required=True)
    sc = sls.add_parser(
        "consolidate", parents=[home_parent], help="conservative consolidation pass"
    )
    sc.add_argument("--limit", type=int, default=20)
    sc.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    sls.add_parser("queue", parents=[home_parent], help="show the replay queue")

    rc = sub.add_parser(
        "reconsolidation",
        parents=[home_parent],
        help="reconsolidation / forgetting (Phase 15, advisory)",
    )
    rcs = rc.add_subparsers(dest="reconsolidation_command", required=True)
    rr = rcs.add_parser("retrieval", parents=[home_parent], help="record a memory retrieval")
    rr.add_argument("memory_id")
    rr.add_argument("--session", dest="session_id", default=None)
    ra = rcs.add_parser("activation", parents=[home_parent], help="record a retrieval outcome")
    ra.add_argument("memory_id")
    ra.add_argument("outcome", choices=("correct", "irrelevant", "contradicted"))
    ra.add_argument("--session", dest="session_id", default=None)
    rh = rcs.add_parser("heat", parents=[home_parent], help="set heat state")
    rh.add_argument("memory_id")
    rh.add_argument("heat", choices=("HOT", "WARM", "COLD", "ARCHIVED"))
    rcs.add_parser(
        "decay", parents=[home_parent], help="decay pass (dry run unless --apply)"
    ).add_argument("--apply", action="store_true")

    sk = sub.add_parser(
        "skills", parents=[home_parent], help="skill forge (Phase 16, candidates only)"
    )
    sks = sk.add_subparsers(dest="skills_command", required=True)
    sf = sks.add_parser("forge", parents=[home_parent], help="forge a candidate from episodes")
    sf.add_argument("name")
    sf.add_argument("episode_ids", nargs="+")
    sv = sks.add_parser("validate", parents=[home_parent], help="validate candidate structure")
    sv.add_argument("name")
    st = sks.add_parser(
        "eval", parents=[home_parent], help="run trigger/workflow/regression/security evals"
    )
    st.add_argument("name")
    st.add_argument("--cases", default=None, help="eval cases JSON (default: repo fixture)")
    ssh = sks.add_parser(
        "shadow", parents=[home_parent], help="move a fully-evaluated candidate to shadow"
    )
    ssh.add_argument("name")
    ssh.add_argument(
        "--cases", default=None, help="eval cases JSON (REQUIRED; default: repo fixture)"
    )
    sks.add_parser("audit", parents=[home_parent], help="audit skill lifecycle consistency")
    sks.add_parser("list", parents=[home_parent], help="list candidates and shadow skills")

    rt = sub.add_parser(
        "router",
        parents=[home_parent],
        help="sparse skill router (Phase 17/23; active+candidate+shadow pool)",
    )
    rts = rt.add_subparsers(dest="router_command", required=True)
    rr2 = rts.add_parser(
        "route", parents=[home_parent], help="route a task to skills (report only)"
    )
    rr2.add_argument("task")
    rr2.add_argument("--max-active", type=int, default=3)
    rts.add_parser("eval", parents=[home_parent], help="run the router fixture eval")

    cr = sub.add_parser("credit", parents=[home_parent], help="credit assignment (Phase 18)")
    crs = cr.add_subparsers(dest="credit_command", required=True)
    ca = crs.add_parser("assign", parents=[home_parent], help="explicitly assign credit levels")
    ca.add_argument("session_id")
    ca.add_argument("--direct", nargs="*", default=[])
    ca.add_argument("--contributory", nargs="*", default=[])
    ca.add_argument("--correlated", nargs="*", default=[])
    crep = crs.add_parser("report", parents=[home_parent], help="aggregate credit events")
    crep.add_argument("--session", dest="session_id", default=None)
    cf = crs.add_parser(
        "counterfactual", parents=[home_parent], help="with/without-skill routing eval"
    )
    cf.add_argument("skill_name")
    cf.add_argument("tasks_file")

    opt = sub.add_parser(
        "optimize", parents=[home_parent], help="governed optimization lifecycle"
    )
    opts = opt.add_subparsers(dest="optimization_command", required=True)
    opp = opts.add_parser("propose", parents=[home_parent], help="create an immutable proposal")
    opp.add_argument("fingerprint_id")
    opp.add_argument("--skill", dest="skill_name", required=True)
    opp.add_argument("--intervention-hash", required=True)
    opp.add_argument("--mode", choices=optimization.MODES, default="shadow")
    opp.add_argument("--json", action="store_true")
    ope = opts.add_parser("evaluate", parents=[home_parent], help="attach evaluation evidence")
    ope.add_argument("proposal_id")
    ope.add_argument("--result-json", type=Path, required=True)
    ope.add_argument("--json", action="store_true")
    opa = opts.add_parser("activate", parents=[home_parent], help="activate a proved proposal")
    opa.add_argument("proposal_id")
    opa.add_argument("--session", dest="session_id", default="")
    opa.add_argument("--json", action="store_true")
    opr = opts.add_parser("rollback", parents=[home_parent], help="delegate guarded rollback")
    opr.add_argument("proposal_id")
    opr.add_argument("trigger_id")
    opr.add_argument("--reason", required=True)
    opr.add_argument("--json", action="store_true")
    opshow = opts.add_parser("show", parents=[home_parent], help="show latest proposal version")
    opshow.add_argument("proposal_id")
    opshow.add_argument("--json", action="store_true")
    eg = sub.add_parser(
        "engrams", parents=[home_parent], help="workflow engrams (Phase 19, candidates only)"
    )
    fr = sub.add_parser(
        "frontier", parents=[home_parent], help="frontier memory review gate (Phase 21)"
    )
    im = sub.add_parser(
        "immune", parents=[home_parent], help="immune system rollback triggers (Phase 22)"
    )
    pm = sub.add_parser(
        "promote", parents=[home_parent], help="promote a skill with all guards (Phase 23)"
    )
    pm.add_argument("skill_name")
    pm.add_argument("from_level", choices=["shadow", "candidate", "active"])
    pm.add_argument("to_level", choices=["shadow", "candidate", "active"])
    pm.add_argument("--session", dest="session_id", default="")
    pd = sub.add_parser("demote", parents=[home_parent], help="demote a skill (records reason)")
    pd.add_argument("skill_name")
    pd.add_argument("to_level", choices=["shadow", "candidate"])
    pd.add_argument("--reason", required=True)
    sub.add_parser("promotions", parents=[home_parent], help="promotion status + history")

    ims = im.add_subparsers(dest="immune_command", required=True)
    imp = ims.add_parser("policy", parents=[home_parent], help="register a guarded policy")
    imp.add_argument("policy_id")
    imp.add_argument("--trigger", dest="rollback_trigger", required=True)
    imp.add_argument("--target", dest="rollback_target", required=True)
    imp.add_argument("--backup-of", dest="backup_of", required=True)
    imt = ims.add_parser("trigger", parents=[home_parent], help="register a metric trigger")
    imt.add_argument("trigger_id")
    imt.add_argument(
        "--metric",
        choices=[
            "tests_failed",
            "f1_delta",
            "noise_delta",
            "compile_error_count",
            "success_rate_delta",
        ],
        required=True,
    )
    imt.add_argument("--operator", choices=["<", "<=", ">", ">=", "==", "!="], required=True)
    imt.add_argument("--value", type=float, required=True)
    imt.add_argument("--window", type=int, required=True)
    imi = ims.add_parser("ingest", parents=[home_parent], help="ingest a metric sample")
    imi.add_argument("metric")
    imi.add_argument("value", type=float)
    imi.add_argument("--run", dest="run_id", default="cli")
    imc = ims.add_parser("check", parents=[home_parent], help="evaluate triggers")
    imc.add_argument("--policy", dest="policy_id", default=None)
    imr = ims.add_parser("rollback", parents=[home_parent], help="guarded rollback")
    imr.add_argument("policy_id")
    imr.add_argument("trigger_id")
    imr.add_argument("--reason", required=True)
    ims.add_parser("log", parents=[home_parent], help="rollback log")

    frs = fr.add_subparsers(dest="frontier_command", required=True)
    frr = frs.add_parser("review", parents=[home_parent], help="record a manual review")
    frr.add_argument("change_id")
    frr.add_argument("--summary", required=True)
    frr.add_argument("--risk", choices=["low", "medium", "high"], required=True)
    frr.add_argument("--reviewer", required=True)
    frr.add_argument("--verdict", choices=["approve", "reject", "request_changes"], required=True)
    frr.add_argument("--notes", default="")
    fq = frs.add_parser("require", parents=[home_parent], help="require review before activation")
    fq.add_argument("change_id")
    fq.add_argument("--summary", required=True)
    fq.add_argument("--risk", choices=["low", "medium", "high"], default="high")
    fg = frs.add_parser("gate", parents=[home_parent], help="activation gate check")
    fg.add_argument("change_id")
    fst = frs.add_parser("status", parents=[home_parent], help="review-gate status")
    fst.add_argument("--change-id", dest="change_id", default=None)
    frs.add_parser("pending", parents=[home_parent], help="list held (unreviewed) changes")

    xm = sub.add_parser("models", parents=[home_parent], help="cross-model memory (Phase 20)")
    xms = xm.add_subparsers(dest="models_command", required=True)
    xmr = xms.add_parser("record", parents=[home_parent], help="record a model skill outcome")
    xmr.add_argument("model_id")
    xmr.add_argument("skill_name")
    xmr.add_argument("task")
    xmr.add_argument(
        "--success",
        dest="success",
        type=lambda v: v.lower() in ("1", "true", "yes"),
        default=False,
    )
    xmr.add_argument("--noise", type=int, default=0)
    xmr.add_argument("--f1", type=float, default=0.0)
    xmr.add_argument("--session", dest="session_id", default="")
    xmt = xms.add_parser("transfer", parents=[home_parent], help="transfer test between two models")
    xmt.add_argument("skill_name")
    xmt.add_argument("model_a")
    xmt.add_argument("model_b")
    xmg = xms.add_parser(
        "policy", parents=[home_parent], help="global policy stats (contamination guard)"
    )
    xmg.add_argument("skill_name")
    xma = xms.add_parser("add", parents=[home_parent], help="record a model profile")
    xma.add_argument("model_id")
    xma.add_argument("--family", default="")
    xma.add_argument("--capabilities", default="")
    xms.add_parser("report", parents=[home_parent], help="model skill report")

    egs = eg.add_subparsers(dest="engrams_command", required=True)
    ed = egs.add_parser("detect", parents=[home_parent], help="detect repeated skill sequences")
    ed.add_argument("sequences_file")
    ed.add_argument("--min-support", type=int, default=2)
    ew = egs.add_parser("write", parents=[home_parent], help="write a candidate engram")
    ew.add_argument("name")
    ew.add_argument("--skill", dest="skills", action="append", required=True)
    ew.add_argument("--trigger", dest="trigger_note", default="")
    ev = egs.add_parser("validate", parents=[home_parent], help="validate an engram")
    ev.add_argument("name")
    egs.add_parser("list", parents=[home_parent], help="list candidate engrams")

    tel = sub.add_parser("telemetry", parents=[home_parent], help="agent telemetry (Phase 2)")
    ts = tel.add_subparsers(dest="telemetry_command", required=True)
    trep = ts.add_parser("report", help="aggregate telemetry records")
    trep.add_argument("--since", default=None, help="only records with ts >= value")
    trep.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    ts.add_parser("validate", help="validate telemetry records")

    calibrate = sub.add_parser("calibrate", parents=[home_parent], help="calibrate measured token ratios")
    calibrate_sub = calibrate.add_subparsers(dest="calibrate_command", required=True)
    calibrate_tokens = calibrate_sub.add_parser(
        "tokens", parents=[home_parent], help="fit chars-per-token from telemetry"
    )
    calibrate_tokens.add_argument("--json", action="store_true", dest="as_json")

    heartbeat_parser = sub.add_parser(
        "heartbeat", parents=[home_parent], help="event-driven local heartbeat"
    )
    heartbeat_sub = heartbeat_parser.add_subparsers(dest="heartbeat_command", required=True)
    heartbeat_run = heartbeat_sub.add_parser(
        "run",
        parents=[home_parent],
        help="run heartbeat if due",
    )
    heartbeat_run.add_argument("--event", required=True)
    heartbeat_run.add_argument("--session", dest="session_id", required=True)
    heartbeat_run.add_argument("--repo", type=Path, default=None)
    heartbeat_run.add_argument("--force", action="store_true")
    heartbeat_run.add_argument("--json", action="store_true")

    p4_parser = sub.add_parser(
        "p4", parents=[home_parent], help="bounded P4 pulse (heartbeat + shutdown Radar, Task 7)"
    )
    p4_sub = p4_parser.add_subparsers(dest="p4_command", required=True)
    p4_pulse = p4_sub.add_parser("pulse", parents=[home_parent], help="run one bounded P4 pulse")
    p4_pulse.add_argument("--event", required=True)
    p4_pulse.add_argument("--session", dest="session_id", required=True)
    p4_pulse.add_argument("--repo", type=Path, default=None)
    p4_pulse.add_argument("--project-id", dest="project_id", default=None)
    p4_pulse.add_argument("--force", action="store_true")
    p4_pulse.add_argument("--no-telemetry", dest="emit_telemetry", action="store_false")
    p4_pulse.add_argument("--json", action="store_true")



    gov = sub.add_parser(
        "governor",
        parents=[home_parent],
        help="token governor & ROI analysis (Phase 1)",
    )
    govs = gov.add_subparsers(dest="governor_command", required=True)

    gov_rep = govs.add_parser("report", parents=[home_parent], help="per-session token report")
    gov_rep.add_argument("--session", default=None, help="filter to one session ID")
    gov_rep.add_argument("--since", default=None, help="ISO timestamp filter")
    gov_rep.add_argument("--json", action="store_true", help="machine-readable output")

    gov_flags = govs.add_parser("flags", parents=[home_parent], help="show feature flags & sources")
    gov_flags.add_argument("--json", action="store_true", help="machine-readable output")

    gov_cmp = govs.add_parser("compare", parents=[home_parent], help="ROI analysis: on vs off arm")
    gov_cmp.add_argument("--on", required=True, help="session ID or glob for Brain ON")
    gov_cmp.add_argument("--off", required=True, help="session ID or glob for Brain OFF")
    gov_cmp.add_argument("--json", action="store_true", help="machine-readable output")

    gov_profs = govs.add_parser(
        "profiles",
        parents=[home_parent],
        help="list ablation profiles (§4.2, §24.2)",
    )
    gov_profs.add_argument("--json", action="store_true", help="machine-readable output")

    gov_prof = govs.add_parser(
        "profile",
        parents=[home_parent],
        help="show flags for an ablation profile",
    )
    gov_prof.add_argument("name", help="ablation profile name, e.g. A_BRAIN_OFF, I_FULL_V1")
    gov_prof.add_argument(
        "--env", action="store_true", help="output environment variable export format"
    )
    gov_prof.add_argument("--json", action="store_true", help="machine-readable output")

    gov_budget = govs.add_parser(
        "check-budget",
        parents=[home_parent],
        help="T3.1: hard/soft session or worker token budget state",
    )
    gov_budget.add_argument("--session", required=True, help="host session id")
    gov_budget.add_argument(
        "--role", default="driver", help="role profile; 'worker' uses [budgets] worker_tokens"
    )
    gov_budget.add_argument("--json", action="store_true", help="machine-readable output")

    fw = sub.add_parser(
        "firewall",
        parents=[home_parent],
        help="Observation Firewall: tool output reduction & recovery (Phase 2)",
    )
    fws = fw.add_subparsers(dest="firewall_command", required=True)

    fw_red = fws.add_parser(
        "reduce",
        parents=[home_parent],
        help="reduce bulky tool output deterministically",
    )
    fw_red.add_argument(
        "input_path", nargs="?", default=None, help="file path or stdin if omitted"
    )
    fw_red.add_argument(
        "--kind",
        default=None,
        help="reducer kind (pytest, compiler, git, search, json, logs, build, doctor, generic)",
    )
    fw_red.add_argument(
        "--command",
        dest="exec_command",
        default="",
        help="command executed (for kind auto-detection)",
    )
    fw_red.add_argument("--tool", default="", help="tool name (e.g. bash, pytest)")
    fw_red.add_argument("--session", default=None, help="session ID for artifact metadata")
    fw_red.add_argument("--json", action="store_true", help="output full ReducerResult as JSON")

    fw_exp = fws.add_parser(
        "expand",
        parents=[home_parent],
        help="losslessly expand a reduced artifact",
    )
    fw_exp.add_argument(
        "ref", help="artifact hash, prefix, or [brain-artifact:sha256:hash] handle"
    )

    fw_kinds = fws.add_parser(
        "kinds",
        parents=[home_parent],
        help="list available deterministic reducer kinds",
    )
    fw_kinds.add_argument("--json", action="store_true", help="machine-readable output")

    vm = sub.add_parser(
        "vmem",
        parents=[home_parent],
        help="Context Virtual Memory: session object paging & hot context (Phase 3)",
    )
    vms = vm.add_subparsers(dest="vmem_command", required=True)

    vm_st = vms.add_parser(
        "store", parents=[home_parent], help="store a transient session object"
    )
    vm_st.add_argument("session_id", help="host session ID")
    vm_st.add_argument(
        "kind",
        help="object kind (e.g. WORKER_FINDING, TEST_EVIDENCE, DECISION, BLOCKER)",
    )
    vm_st.add_argument("title", help="object title")
    vm_st.add_argument(
        "content_path", nargs="?", default=None, help="file path or stdin if omitted"
    )
    vm_st.add_argument("--summary", default="", help="optional short summary")
    vm_st.add_argument("--pinned", action="store_true", help="pin object to avoid eviction")
    vm_st.add_argument(
        "--metadata",
        default=None,
        help="JSON object merged into the stored object's metadata (e.g. "
        '\'{"toolCallId": "..."}\' or \'{"deliveryId": "..."}\'); '
        "threads into VMemStore.store_object's existing metadata field",
    )
    vm_st.add_argument("--json", action="store_true", help="output JSON")

    vm_ls = vms.add_parser("list", parents=[home_parent], help="list session objects")
    vm_ls.add_argument("session_id", help="host session ID")
    vm_ls.add_argument(
        "--state",
        default=None,
        help="filter by residency state (RESIDENT, EVICTED, etc.)",
    )
    vm_ls.add_argument("--kind", default=None, help="filter by kind")
    vm_ls.add_argument("--json", action="store_true", help="output JSON")

    vm_pg = vms.add_parser("page", parents=[home_parent], help="page-in (fault-in) an object by ID")
    vm_pg.add_argument("session_id", help="host session ID")
    vm_pg.add_argument("obj_id", help="object ID (e.g. obj-123456789abc)")
    vm_pg.add_argument("--json", action="store_true", help="output JSON")

    # Part D (RC4 pass): additive, does NOT change `page`'s existing contract
    # above. `resolve` fault-in's the object via the same VMemStore.fault_in
    # AND then resolves it through its durable backing source (deliveries+
    # memories for RESEARCH_RESULT, the artifact store for TOOL_OBSERVATION,
    # raw passthrough otherwise) — see vmem.resolve_object.
    vm_rs = vms.add_parser(
        "resolve",
        parents=[home_parent],
        help="fault-in an object AND resolve it through its durable backing source",
    )
    vm_rs.add_argument("session_id", help="host session ID")
    vm_rs.add_argument("obj_id", help="object ID (e.g. obj-123456789abc)")
    vm_rs.add_argument("--json", action="store_true", help="output JSON")

    vm_hc = vms.add_parser("hot-context", parents=[home_parent], help="render minimal hot context")
    vm_hc.add_argument("session_id", help="host session ID")
    vm_hc.add_argument("--budget", type=int, default=1500, help="token budget")
    vm_hc.add_argument("--json", action="store_true", help="output JSON")

    # Defect B (RC4 proactive-paging-repair pass): additive, does not reuse/
    # alter `compact-prep`/`page`/`resolve` above. `claim-pages` atomically
    # attempts to transition a small, bounded set of caller-specified
    # objects from a pre-page residency state (RESIDENT/FAULTED_IN,
    # unpinned) to EVICTED -- the proactive counterpart to
    # `prepare_compaction`'s compaction-triggered eviction -- see
    # VMemStore.claim_pages. Bounded, fast, deterministic: no LLM, no
    # retrieval, no free text.
    vm_cl = vms.add_parser(
        "claim-pages",
        parents=[home_parent],
        help="atomically claim a bounded set of pre-page objects for proactive paging (-> EVICTED)",
    )
    vm_cl.add_argument("session_id", help="host session ID")
    vm_cl.add_argument("--json", action="store_true", help="output JSON")

    vm_cp = vms.add_parser("compact-prep", parents=[home_parent], help="prepare for compaction")
    vm_cp.add_argument("session_id", help="host session ID")
    vm_cp.add_argument("--json", action="store_true", help="output JSON")

    vm_cr = vms.add_parser("compact-resume", parents=[home_parent], help="resume after compaction")
    vm_cr.add_argument("session_id", help="host session ID")
    vm_cr.add_argument("--budget", type=int, default=1500, help="token budget")

    vm_ev = vms.add_parser("evict", parents=[home_parent], help="evict unpinned objects to budget")
    vm_ev.add_argument("session_id", help="host session ID")
    vm_ev.add_argument("--budget", type=int, default=1500, help="token budget ceiling")
    vm_ev.add_argument("--json", action="store_true", help="output JSON")

    ac = sub.add_parser(
        "action-cache",
        parents=[home_parent],
        help="Proof-Carrying Action Cache: pure action replay & safety proofs (Phase 4)",
    )
    acs = ac.add_subparsers(dest="action_cache_command", required=True)

    ac_stats = acs.add_parser(
        "stats", parents=[home_parent], help="show action cache statistics"
    )
    ac_stats.add_argument("--json", action="store_true", help="output JSON")

    ac_get = acs.add_parser(
        "get",
        parents=[home_parent],
        help="get and validate cached action by key",
    )
    ac_get.add_argument("action_key", help="deterministic action key hash")
    ac_get.add_argument("--json", action="store_true", help="output JSON")

    ac_inv = acs.add_parser(
        "invalidate",
        parents=[home_parent],
        help="invalidate entries by path dependency",
    )
    ac_inv.add_argument("--path", default=None, help="target path that changed")
    ac_inv.add_argument(
        "--all",
        dest="invalidate_all",
        action="store_true",
        help="invalidate all entries",
    )
    ac_inv.add_argument("--json", action="store_true", help="output JSON")

    acs.add_parser("clear", parents=[home_parent], help="clear entire action cache")

    ac_search = acs.add_parser(
        "search",
        parents=[home_parent],
        help="deterministic code search over git-tracked files, cached and "
        "gated by a scoped dirty-worktree fingerprint (Phase R5: narrowest "
        "Brain-owned execution-bypass layer — Prime's tool_call hook cannot "
        "itself skip execution)",
    )
    ac_search.add_argument("pattern", help="regular expression to search for")
    ac_search.add_argument(
        "--path", default=None, help="directory to search (default: brain home)"
    )
    ac_search.add_argument(
        "--max-matches", type=int, default=200, help="cap on returned matches"
    )
    ac_search.add_argument("--json", action="store_true", help="output JSON")

    wp = sub.add_parser(
        "worker-plane",
        parents=[home_parent],
        help="Driver/Worker Plane concurrency guard & packet broker (Phase R7: "
        "the actual Brain-owned enforcement point — Prime exposes no "
        "extension hook for subagent/worker spawn, see "
        "outputs/reports/rc4/07-worker-plane-live.md)",
    )
    wps = wp.add_subparsers(dest="worker_plane_command", required=True)

    wp_spawn = wps.add_parser(
        "spawn", parents=[home_parent], help="spawn a worker if under the concurrency ceiling"
    )
    wp_spawn.add_argument("session_id", help="host session ID")
    wp_spawn.add_argument("subtask", help="worker subtask description")
    wp_spawn.add_argument("--target-files", nargs="*", default=None)
    wp_spawn.add_argument("--relevant-symbols", nargs="*", default=None)
    wp_spawn.add_argument("--context-capsule", default="")
    wp_spawn.add_argument("--max-workers", type=int, default=None, help="concurrency ceiling")
    wp_spawn.add_argument("--json", action="store_true", help="output JSON")

    wp_complete = wps.add_parser(
        "complete", parents=[home_parent], help="record a worker's completion"
    )
    wp_complete.add_argument("session_id", help="host session ID")
    wp_complete.add_argument("worker_id", help="worker ID returned by spawn")
    wp_complete.add_argument(
        "--status",
        choices=["COMPLETED", "FAILED", "CANCELLED"],
        default="COMPLETED",
    )
    wp_complete.add_argument("--summary", default="")
    wp_complete.add_argument("--finding", dest="findings", action="append", default=[])
    wp_complete.add_argument("--tokens-used", type=int, default=0)
    wp_complete.add_argument("--json", action="store_true", help="output JSON")

    wp_status = wps.add_parser(
        "status", parents=[home_parent], help="show active worker count vs the ceiling"
    )
    wp_status.add_argument("session_id", help="host session ID")
    wp_status.add_argument("--max-workers", type=int, default=None, help="concurrency ceiling")
    wp_status.add_argument("--json", action="store_true", help="output JSON")
    wp_reap = wps.add_parser(
        "reap", parents=[home_parent], help="fail expired or unacknowledged worker tasks"
    )
    wp_reap.add_argument("--json", action="store_true", help="output JSON")

    # Phase R9: the "prepare" half of fresh-verifier plumbing already exists
    # as `second_brain verify <session_id> <repo>` (verify.build_verifier_brief,
    # Phase 7) — a real, working, backward-reconstruction brief builder. This
    # command is only the missing "record" half: capture a real fresh
    # session's raw response + provenance and parse its verdict. It cannot
    # produce PASS/FAIL without a raw-response file that already exists. See
    # outputs/reports/rc4/09-fresh-verifier.md.
    fv = sub.add_parser(
        "fresh-verifier",
        parents=[home_parent],
        help="record a real fresh verifier session's raw response and parse "
        "its verdict (Phase R9) — pair with `second_brain verify` for the brief",
    )
    fvs = fv.add_subparsers(dest="fresh_verifier_command", required=True)

    fv_record = fvs.add_parser(
        "record",
        parents=[home_parent],
        help="parse the verdict from a real fresh session's raw response (never fabricated)",
    )
    fv_record.add_argument("--out", required=True, help="output directory for the evidence bundle")
    fv_record.add_argument(
        "--prompt-file", required=True, help="the brief/prompt the fresh session was actually given"
    )
    fv_record.add_argument(
        "--raw-response", required=True, help="path to the fresh session's raw output"
    )
    fv_record.add_argument("--provider", default=None)
    fv_record.add_argument("--model", default=None)
    fv_record.add_argument("--host", default=None)
    fv_record.add_argument("--session-id", default=None, help="omit if the host exposes none")
    fv_record.add_argument("--input-tokens", type=int, default=None)
    fv_record.add_argument("--output-tokens", type=int, default=None)
    fv_record.add_argument("--json", action="store_true", help="output JSON")

    ds = sub.add_parser(
        "delta-sync",
        parents=[home_parent],
        help="Delta Sync: minimal incremental memory updates (Phase 5)",
    )
    dss = ds.add_subparsers(dest="delta_sync_command", required=True)

    ds_diff = dss.add_parser(
        "diff",
        parents=[home_parent],
        help="compute delta between two memory JSON files",
    )
    ds_diff.add_argument("base_file", help="path to base memory JSON file (or 'null' for new)")
    ds_diff.add_argument("target_file", help="path to target memory JSON file")
    ds_diff.add_argument("--json", action="store_true", help="output JSON")

    ds_apply = dss.add_parser(
        "apply",
        parents=[home_parent],
        help="apply a delta packet to a base memory JSON file",
    )
    ds_apply.add_argument("base_file", help="path to base memory JSON file")
    ds_apply.add_argument("delta_file", help="path to delta packet JSON file")
    ds_apply.add_argument("--json", action="store_true", help="output JSON")

    ds_sync = dss.add_parser(
        "sync",
        parents=[home_parent],
        help="sync memory list against session delivery state",
    )
    ds_sync.add_argument("session_id", help="host session ID")
    ds_sync.add_argument("target_file", help="path to JSON list of target memories")
    ds_sync.add_argument("--recipient", default="driver", help="recipient role (default: driver)")
    ds_sync.add_argument("--json", action="store_true", help="output JSON")

    cas = sub.add_parser(
        "cascade",
        parents=[home_parent],
        help="Hybrid Multi-Tier Retrieval & Cascade: Tiers 0-4 short-circuiting (Phase 6)",
    )
    cass = cas.add_subparsers(dest="cascade_command", required=True)

    cas_q = cass.add_parser(
        "query",
        parents=[home_parent],
        help="query memory via multi-tier cascade",
    )
    cas_q.add_argument("query_text", help="query string or memory ref")
    cas_q.add_argument("--project", default=None, help="project scope ID")
    cas_q.add_argument("--threshold", type=float, default=None, help="confidence threshold override")
    cas_q.add_argument("--json", action="store_true", help="output JSON")

    cass.add_parser("clear-cache", parents=[home_parent], help="clear negative result cache")


    v2 = sub.add_parser("v2", parents=[home_parent], help="v2 corrected-plan surfaces")
    v2s = v2.add_subparsers(dest="v2_command", required=True)
    v2_harness = v2s.add_parser("harness", parents=[home_parent], help="harness adapter profiles")
    v2_harness_sub = v2_harness.add_subparsers(dest="v2_harness_command", required=True)
    v2_cap = v2_harness_sub.add_parser(
        "capabilities",
        parents=[home_parent],
        help="show a harness's capability profile and tier (T4.3)",
    )
    v2_cap.add_argument("harness_id")
    v2_cap.add_argument("--json", action="store_true", help="output JSON")


    v2_learn = v2s.add_parser("learn", parents=[home_parent], help="policy learning and evaluation")
    v2_learn_sub = v2_learn.add_subparsers(dest="v2_learn_command", required=True)
    v2_ope = v2_learn_sub.add_parser(
        "ope",
        parents=[home_parent],
        help="off-policy evaluation via IPS/SNIPS (T5.3)",
    )
    v2_ope.add_argument(
        "--kind",
        default="retrieval",
        choices=sorted(decisions._DECISION_KINDS),
        help="decision kind (default: retrieval)",
    )
    v2_ope.add_argument(
        "--policy",
        required=True,
        help="target policy name (e.g. logging, current, always_inject, inject, holdout)",
    )
    v2_ope.add_argument("--json", action="store_true", help="output JSON")
    return p


def _home(args) -> Path:
    return args.home.resolve() if getattr(args, "home", None) else paths.resolve_home()


def _seed_defaults(home: Path) -> int:
    """Copy missing canonical seed files (VERSION, config, templates) from the package."""
    import shutil

    defaults = Path(__file__).resolve().parent / "defaults"
    if not defaults.is_dir():
        return 0
    seeded = 0
    for src in sorted(defaults.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(defaults)
        dst = home / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        seeded += 1
    return seeded


def cmd_init(args) -> int:
    home = _home(args)
    marker = (home / "VERSION").exists() or (home / "config" / "brain.toml").exists()
    if home.exists():
        content = [p for p in home.iterdir() if p.name != ".git"]
        if content and not marker and not args.force:
            print(
                f"Refusing: {home} exists, is non-empty, and is not a Brain. "
                "Re-run with --force only if you are certain this directory is meant "
                "to become a Brain.",
                file=sys.stderr,
            )
            return 2
    home.mkdir(parents=True, exist_ok=True)
    paths.ensure_layout(home)
    seeded = _seed_defaults(home)

    if not (home / ".git").exists():
        r = subprocess.run(["git", "init"], cwd=home, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"git init failed: {r.stderr.strip()}", file=sys.stderr)
            return 1

    applied = db.migrate(db.db_path(home))
    print(f"Brain initialized at {home}" + (f" (seeded {seeded} default files)" if seeded else ""))
    print(
        f"Database ready: {db.db_path(home)}"
        + (f" (applied migrations {applied})" if applied else " (already current)")
    )
    print("Next steps: `brainctl doctor`, `brainctl project add <repo>`, `brainctl status`")
    return 0


def cmd_doctor(args) -> int:
    import json

    result = doctor_mod.run_doctor(
        _home(args),
        repo=args.repo,
        session_id=args.session_id,
    )
    payload = {
        "home": str(result.home),
        "failed": result.failed,
        "warnings": [check.name for check in result.warnings],
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail}
            for check in result.checks
        ],
    }
    if args.out is not None:
        args.out.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(doctor_mod.format_result(result))
    return 1 if result.failed else 0


def cmd_status(args) -> int:
    home = _home(args)
    print(f"Brain home:  {home}")
    vf = home / "VERSION"
    print(f"Version:     {vf.read_text(encoding='utf-8').strip() if vf.exists() else 'unknown'}")
    try:
        conn = db.connect(db.db_path(home))
        try:
            v = conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0]
            n_projects = conn.execute("SELECT COUNT(*) FROM projects WHERE active = 1").fetchone()[
                0
            ]
            print(f"DB:          {db.db_path(home)} (schema v{v}, {n_projects} active projects)")
        finally:
            conn.close()
    except Exception as exc:  # sqlite3.Error etc.
        print(f"DB:          unavailable ({exc})")
    backups = backup_mod.list_backups(home)
    print(f"Backups:     {len(backups)}" + (f", latest {backups[0].name}" if backups else ""))
    return 0


def cmd_project(args) -> int:
    home = _home(args)
    if args.project_command == "add":
        proj, created, changes = registry.attach_project(
            home,
            args.repo,
            name=args.name,
            project_id=args.project_id,
            with_marker=not args.no_marker,
            with_manifest=not args.no_manifest,
        )
        verb = "Attached" if created else "Already attached (refreshed)"
        print(f"{verb} project {proj.name!r} (id {proj.id})")
        print(f"Brain project dir: {proj.brain_project_path}")
        if changes.get("manifest_created"):
            print(f"Wrote manifest: {Path(args.repo) / '.brain' / 'project.toml'}")
        if changes.get("marker_added"):
            print(f"Added AGENTS.md marker: {Path(args.repo) / 'AGENTS.md'}")
        return 0
    if args.project_command == "list":
        projects = registry.list_projects(home, include_inactive=args.inactive)
        if not projects:
            print("No registered projects.")
            return 0
        for p in projects:
            print(f"{p.id}  {p.name}  {p.repo_path or '-'}")
        return 0
    if args.project_command == "status":
        st = registry.project_status(home, args.key)
        for k, v in st.items():
            print(f"{k:16s} {v}")
        return 0
    if args.project_command == "remove":
        out = registry.remove_project(home, args.key, purge=args.purge)
        print(f"Removed project {out['name']!r} (id {out['id']}); purged={out['purged']}")
        return 0
    if args.project_command == "detach":
        changes = registry.detach_project(home, args.key)
        print(f"Detached {changes['name']!r} (id {changes['id']})")
        for k in ("marker_removed", "agents_file_deleted", "manifest_removed", "deactivated"):
            if k in changes:
                print(f"{k:20s} {changes[k]}")
        return 0
    return 2


def cmd_artifact(args) -> int:
    home = _home(args)
    if args.artifact_command == "store":
        if args.path:
            info = artifacts.store_file(
                home, args.path, args.kind, tool=args.tool, session=args.session
            )
        else:
            # P3-F: read stdin as EXACT BYTES (text mode would translate
            # CRLF -> LF and break content-addressed sha256 recovery).
            data = sys.stdin.buffer.read()
            info = artifacts.store_bytes(
                home, data, args.kind, tool=args.tool, session=args.session
            )
        artifacts.add_ref(home, info["hash"], owner="cli-manual")
        print(info["handle"])
        if not args.no_distill:
            print("Distilled:")
            print(info["distilled"])
        print(artifacts.recover_hint(info["hash"]))
        return 0
    if args.artifact_command == "expand":
        sys.stdout.buffer.write(artifacts.expand(home, args.hash_prefix))
        return 0
    if args.artifact_command == "list":
        for m in artifacts.list_artifacts(home):
            print(
                f"{m['created_at']} {m['hash'][:12]} {m['size']:8d} {m['kind']:10s} "
                f"{m['tool'] or '-'}"
            )
        return 0
    return 2


def cmd_risk(args) -> int:
    result = risk.assess_risk(args.repo, args.files, user_criticality=args.criticality)
    print(f"Risk: {result['level']} (score {result['score']})")
    for s in result["signals"]:
        if s["points"]:
            print(f"  {s['name']:20s} {s['points']}  {s['detail']}")
    if args.verification_ladder:
        # P3-G: compact risk-adaptive verification ladder for the RESULTING
        # level (user criticality already applied — the ladder follows it).
        payload = verify.verification_ladder_payload(result["level"], home=_home(args))
        print(f"Verification ladder ({payload['level']}):")
        for index, action in enumerate(payload["actions"], 1):
            print(f"  {index}. {action}")
        verifier_line = (
            "REQUIRED (brainctl verify build-brief)"
            if payload["independent_verifier"]
            else "not required"
        )
        print("  independent verifier: " + verifier_line)
        approval_line = "REQUIRED" if payload["approval_required"] else "not required"
        print("  human approval: " + approval_line)
    return 0


def cmd_v2(args) -> int:
    if args.v2_command == "harness" and args.v2_harness_command == "capabilities":
        home = _home(args)
        harness_id = args.harness_id
        tier = capabilities.harness_tier(home, harness_id)
        payload = {
            "harness_id": harness_id,
            "tier": tier,
            "tier_behavior": capabilities.TIER_BEHAVIOR[tier],
            "capabilities": capabilities.list_capabilities(home, harness_id),
        }
        if args.json:
            print(contracts.canonical_json(payload))
        else:
            print(f"{harness_id}: {tier} -- {payload['tier_behavior']}")
            for name in sorted(payload["capabilities"]):
                row = payload["capabilities"][name]
                supported = row["supported"]
                state = "unknown" if supported is None else ("yes" if supported else "no")
                print(
                    f"  {name:20s} supported={state:7s} version={row['version']}"
                    f" observed_at={row['observed_at']}"
                )
        return 0
    if args.v2_command == "learn" and args.v2_learn_command == "ope":
        home = _home(args)
        if args.kind not in decisions._DECISION_KINDS:
            raise BrainError(f"kind must be one of {sorted(decisions._DECISION_KINDS)}")
        records = decisions.list_decisions(home, kind=args.kind)
        try:
            result = economics.ope_ips(records, args.policy)
        except ValueError as exc:
            raise BrainError(str(exc)) from exc
        ess = result["ess"]
        n = result["n"]
        val = result["value"]
        val_snips = result["value_snips"]
        if ess < 30.0:
            payload = {
                "status": "INSUFFICIENT_LOGGED_DATA",
                "n": n,
                "ess": ess,
                "value": val,
                "value_snips": val_snips,
            }
            if args.json:
                print(contracts.canonical_json(payload))
            else:
                print(f"INSUFFICIENT_LOGGED_DATA (ess={ess:.1f} < 30, n={n})")
            return 1

        payload = {
            "status": "OK",
            "n": n,
            "ess": ess,
            "value": val,
            "value_snips": val_snips,
        }
        if args.json:
            print(contracts.canonical_json(payload))
        else:
            print(
                f"OPE IPS: value={val:.4f} value_snips={val_snips:.4f} "
                f"ess={ess:.1f} n={n} policy={args.policy} kind={args.kind}"
            )
        return 0
    return 2


def cmd_radar(args) -> int:
    import json

    home = _home(args)
    detector = radar.ImprovementRadar(home)
    if args.radar_command == "observe":
        started = perf_counter()
        candidates = detector.observe_session(
            args.session_id,
            project_id=args.project_id,
            task_id=args.task_id,
        )
        fingerprints_by_id: dict[str, dict] = {}
        for candidate in candidates:
            for fingerprint in candidate.get("fingerprints", []):
                fingerprint_id = str(fingerprint.get("fingerprint_id", ""))
                existing = fingerprints_by_id.get(fingerprint_id)
                if existing is None or (
                    float(fingerprint.get("impact_score", 0))
                    * int(fingerprint.get("occurrence_count", 0))
                    > float(existing.get("impact_score", 0))
                    * int(existing.get("occurrence_count", 0))
                ):
                    fingerprints_by_id[fingerprint_id] = fingerprint
        fingerprints = sorted(
            fingerprints_by_id.values(),
            key=lambda item: (
                -(float(item.get("impact_score", 0)) * int(item.get("occurrence_count", 0))),
                str(item.get("fingerprint_id", "")),
            ),
        )
        payload = {
            "session_id": args.session_id,
            "project_id": args.project_id,
            "repo": str(args.repo.resolve()),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "fingerprints": fingerprints,
            "radar_overhead_ms": round((perf_counter() - started) * 1000, 3),
        }
        if args.out is not None:
            args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    else:
        payload = detector.validate_candidate(args.candidate_id)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload)
    return 0


def cmd_verify(args) -> int:
    home = _home(args)
    if args.verify_command == "build-brief":
        path = verify.build_verifier_brief(home, args.session_id, args.repo)
        print(f"Verifier brief: {path}")
        return 0
    if args.verify_command == "independent":
        import json

        from . import contracts, fresh_verifier, ledger

        raw_response = args.response_file.read_text(encoding="utf-8")
        if len(raw_response) > 8192:
            raise BrainError("independent verifier response exceeds 8192 characters")
        file_args = {
            "task_hash": args.task_file,
            "requirements_hash": args.requirements_file,
            "diff_hash": args.diff_file,
            "evidence_set_hash": args.evidence_file,
        }
        for field, path in file_args.items():
            if path is None:
                continue
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise BrainError(f"independent verifier evidence file unavailable: {path}") from exc
            supplied = getattr(args, field)
            if supplied and supplied != actual:
                raise BrainError(f"independent verifier hash mismatch: {field}")
            setattr(args, field, actual)
        result = fresh_verifier.bounded_independent_verification(
            raw_response=raw_response,
            verification_id=args.verification_id,
            task_id=args.task_id,
            verifier_session_id=args.verifier_session_id,
            implementation_session_id=args.implementation_session_id,
            task_hash=args.task_hash,
            requirements_hash=args.requirements_hash,
            diff_hash=args.diff_hash,
            evidence_set_hash=args.evidence_set_hash,
            failed_requirement_ids=args.failed_requirement_id,
            unresolved_requirement_ids=args.unresolved_requirement_id,
        )
        event = contracts.BrainLifecycleEvent(
            seq=0,
            event_id=f"independent-verification-{args.verification_id}",
            internal_session_id=ledger.internal_session_id(args.verifier_session_id),
            agent_id=args.verifier_session_id,
            event_type=contracts.LifecycleEventType.INDEPENDENT_VERIFICATION,
            timestamp=datetime.now(UTC).isoformat(),
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload=result,
        )
        with ledger.LedgerStore(home, args.verifier_session_id, host="prime").open(
            create=True
        ) as store:
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(args.verifier_session_id),
                    host="prime",
                    host_session_id=args.verifier_session_id,
                    project_id="",
                    created_at=event.timestamp,
                    status="active",
                    pinned=False,
                    schema_version=contracts.LEDGER_SCHEMA_VERSION,
                )
            )
            result = {**result, "sequence": store.append_events([event])[0]}
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(contracts.canonical_json(result))
        else:
            print(f"{result['verdict']} ({result['freshness']})")
        return 0 if result["verdict"] == "PASS" and result["freshness"] == "fresh" else 1
    if args.verify_command == "gate":
        import json

        from . import contracts, ledger

        action_states: dict[str, str] = {}
        for item in args.action:
            action, separator, state = item.partition("=")
            if (
                not separator
                or not action
                or state not in {"passed", "failed", "unresolved"}
            ):
                raise BrainError(
                    f"invalid --action {item!r}; "
                    "expected ACTION=passed|failed|unresolved"
                )
            action_states[action] = state
        independent_verification = None
        if args.verification_file is not None:
            try:
                loaded = json.loads(args.verification_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrainError(
                    f"invalid independent verification file: {args.verification_file}"
                ) from exc
            if not isinstance(loaded, dict):
                raise BrainError(
                    f"invalid independent verification file: {args.verification_file}"
                )
            independent_verification = loaded
        environment_evidence = None
        if args.environment_file is not None:
            try:
                loaded = json.loads(args.environment_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrainError(
                    f"invalid environment evidence file: {args.environment_file}"
                ) from exc
            if not isinstance(loaded, dict):
                raise BrainError(f"invalid environment evidence file: {args.environment_file}")
            environment_evidence = loaded
        result = verify.evaluate_accuracy_gate(
            home,
            args.session_id,
            args.repo,
            args.files,
            action_states=action_states,
            user_criticality=args.criticality,
            approval_state=args.approval_state,
            task_id=args.task_id,
            parent_session_id=args.parent_session_id,
            worker_session_id=args.worker_session_id,
            independent_verification=independent_verification,
            task_hash=args.task_hash,
            requirements_hash=args.requirements_hash,
            diff_hash=args.diff_hash,
            evidence_set_hash=args.evidence_set_hash,
            environment_evidence=environment_evidence,
            environment_required=args.environment_required,
        )
        event = contracts.BrainLifecycleEvent(
            seq=0,
            event_id=f"accuracy-gate-{result['accuracy_gate_id']}",
            internal_session_id=ledger.internal_session_id(args.session_id),
            agent_id=args.worker_session_id or args.session_id,
            event_type=contracts.LifecycleEventType.ACCURACY_GATE,
            timestamp=datetime.now(UTC).isoformat(),
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload=result,
        )
        with ledger.LedgerStore(home, args.session_id, host="prime").open(create=True) as store:
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(args.session_id),
                    host="prime",
                    host_session_id=args.session_id,
                    project_id="",
                    created_at=event.timestamp,
                    status="active",
                    pinned=False,
                    schema_version=contracts.LEDGER_SCHEMA_VERSION,
                )
            )
            sequence = store.append_events([event])[0]
        result = {**result, "sequence": sequence}
        if args.out is not None:
            args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(contracts.canonical_json(result))
        else:
            print(
                f"{result['risk_level']}: "
                f"{'allowed' if result['completion_allowed'] else 'blocked'} "
                f"({result['decision_reason']})"
            )
        return 0 if result["completion_allowed"] else 1
    return 2


def cmd_env(args) -> int:
    import json

    home = _home(args)
    if args.env_command == "assess":
        result = envsteward.assess(
            home,
            args.repo,
            session_id=args.session_id,
            task_id=args.task_id,
            phase=args.phase,
            expected_fields=args.expected_field,
            requested_changes=args.requested_change,
            result_state=args.mutation_state,
        )
    else:
        result = envsteward.snapshot(home, args.repo, session_id=args.session_id)
    if args.env_command == "assess" and db.db_path(home).exists():
        import uuid

        from . import contracts, ledger

        timestamp = datetime.now(UTC).isoformat()
        event = contracts.BrainLifecycleEvent(
            seq=0,
            event_id=f"environment-assessment-{uuid.uuid4()}",
            internal_session_id=ledger.internal_session_id(args.session_id),
            agent_id=args.session_id,
            event_type=contracts.LifecycleEventType.ENVIRONMENT_ASSESSMENT,
            timestamp=timestamp,
            surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
            ignorable=False,
            payload=result,
        )
        with ledger.LedgerStore(home, args.session_id, host="prime").open(create=True) as store:
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=ledger.internal_session_id(args.session_id),
                    host="prime",
                    host_session_id=args.session_id,
                    project_id=str(result.get("project_id", "")),
                    created_at=timestamp,
                    status="active",
                    pinned=False,
                    schema_version=contracts.LEDGER_SCHEMA_VERSION,
                )
            )
            result = {**result, "sequence": store.append_events([event])[0]}
    if args.env_command == "assess" and args.out is not None:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.as_json:
        print(json.dumps(result, indent=1, default=str))
    else:
        for k, v in result.items():
            print(f"{k:24s} {v}")
    return 0


def cmd_processes(args) -> int:

    home = _home(args)
    if args.processes_command == "register":
        rec = envsteward.register_process(
            home, args.pid, args.exe, token=args.token, session_id=args.session_id
        )
        print(f"Registered pid {rec['pid']} (verified={rec['identity_verified']})")
        return 0
    if args.processes_command == "list":
        for rec in envsteward.list_processes(home):
            print(
                f"{rec['ts']} pid={rec['pid']} exe={rec['exe']} token={rec['token']} "
                f"verified={rec['identity_verified']}"
            )
        return 0
    if args.processes_command == "verify":
        ok = envsteward.verify_process(home, args.pid, args.exe)
        print(f"identity_verified={ok}")
        return 0 if ok else 1
    if args.processes_command == "cleanup":
        result = envsteward.cleanup_owned(home, dry_run=not args.kill)
        print(
            f"killed={result['killed']} skipped={len(result['skipped'])} "
            f"unknown={result['unknown']}"
        )
        for s in result["skipped"]:
            print(f"  skipped: {s}")
        return 0
    return 2


def cmd_episodes(args) -> int:
    home = _home(args)
    if args.episodes_command == "create":
        sections = {}
        for kv in args.sections or []:
            key, _, value = kv.partition("=")
            sections[key] = value
        eid = episodes.create_episode(
            home,
            args.episode_type,
            args.summary,
            project_id=args.project_id,
            session_id=args.session_id,
            task_id=args.task_id,
            evidence_refs=args.evidence_refs,
            prediction_error=args.prediction_error,
            salience=args.salience,
            confidence=args.confidence,
            sections=sections or None,
        )
        print(f"Episode created: {eid}")
        return 0
    if args.episodes_command == "list":
        rows = episodes.list_episodes(
            home, episode_type=args.episode_type, project_id=args.project_id, since=args.since
        )
        for r in rows:
            print(
                f"{r['episode_id']:40s} {r['episode_type']:20s} sal={r['salience']} "
                f"pe={r['prediction_error']} {r['summary'][:70]}"
            )
        return 0
    if args.episodes_command == "show":
        e = episodes.show_episode(home, args.episode_id)
        print(f"id: {e['row']['episode_id']}  type: {e['row']['episode_type']}")
        print(f"path: {e['path']}")
        print()
        print(e["body"])
        return 0
    if args.episodes_command == "search":
        for r in episodes.search_episodes(home, args.term, limit=args.limit):
            print(f"{r['episode_id']:40s} {r['summary'][:80]}")
        return 0
    if args.episodes_command == "annotate":
        episodes.annotate_episode(home, args.episode_id, args.note)
        print(f"Annotated {args.episode_id}")
        return 0
    return 2


def _parse_sources(raw: list[str] | None) -> list[dict] | None:
    """--source kind:ref -> {ref, kind} dicts.

    Kinds episode/test/decision/import are stored as-is; everything else
    (doc:, git:, bare refs) is evidence.
    """
    if not raw:
        return None
    out = []
    for item in raw:
        kind, _, ref = item.partition(":")
        if not ref:
            kind, ref = "evidence", item
        kind = kind.strip() or "evidence"
        if kind not in ("episode", "test", "decision", "import"):
            kind = "evidence"
        out.append({"ref": ref.strip(), "kind": kind})
    return out


def _project_from_cwd(home: Path) -> str | None:
    """Authoritative project resolution for CLI writes: the registered
    project whose root contains the current working directory (plan §10).
    None when no registered project contains cwd — caller must fail clearly."""
    try:
        cwd_abs = os.path.abspath(os.getcwd())
        for proj in registry.list_projects(home):
            root = proj.repo_path
            if root:
                root_abs = os.path.abspath(root)
                try:
                    if os.path.commonpath([cwd_abs, root_abs]) == root_abs:
                        return proj.id
                except ValueError:
                    continue
    except Exception:  # fail open: registry errors -> unresolved -> caller errors
        return None
    return None


def _remember_project(home: Path) -> str:
    """Resolve the project using the shared cwd/environment ladder."""
    from . import autoinject

    return autoinject._resolve_project_id(home, str(Path.cwd()), None)


def cmd_remember(args) -> int:
    claim = args.claim
    if not isinstance(claim, str) or not claim.strip():
        raise BrainError("claim must be a non-empty one-line string")
    if "\r" in claim or "\n" in claim:
        raise BrainError("claim must be a single line")
    home = _home(args)
    source_rows = [
        semantic.capture_evidence(Path.cwd(), specification)
        for specification in args.evidence or []
    ]
    memory_id = semantic.add_memory(
        home,
        claim[:80],
        claim,
        scope="project",
        project_id=_remember_project(home),
        grade=args.grade,
        sources=source_rows,
        origin_class="USER_AUTHORED",
        origin_root_sha=next(
            (row.get("origin_root_sha") for row in source_rows if row.get("origin_root_sha")),
            None,
        ),
    )
    print(memory_id)
    return 0


def cmd_recall(args) -> int:
    from . import autoinject, contracts, freshness

    home = _home(args)
    question = args.question
    if not isinstance(question, str) or not question.strip():
        raise BrainError("question must be a non-empty string")
    project_id = _remember_project(home)
    intent = autoinject.RetrievalIntent(
        task_text=question,
        project_id=project_id,
        agent_id="brainctl",
        role_profile="cli",
        session_id="brainctl-recall-" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:16],
        cwd=str(Path.cwd()),
    )
    decision = autoinject.prepare_injection(home, intent, retrieval_text=question)
    if decision.decision is not contracts.InjectionDecision.INJECT:
        reason = decision.reason.value if decision.reason is not None else "BRAIN_UNAVAILABLE"
        print(f"NO_INJECTION {reason}")
        return 0

    rendered = 0
    for memory_id in decision.selected_ids[:3]:
        row = semantic._row(home, memory_id)
        if row is None:
            continue
        source = next((item for item in semantic._sources(home, memory_id) if item.get("path")), None)
        repo_root = (source or {}).get("repo_id") or str(Path.cwd()) or str(home)
        state = freshness.resolve(home, memory_id, repo_root).get("state", freshness.UNKNOWN)
        body = " ".join(semantic._body_text(home, row).split())[:200]
        title = " ".join(str(row.get("title") or "").split())
        print(f"[{state}] {title} — {body} ({memory_id})")
        rendered += 1
    if rendered == 0:
        print("NO_INJECTION NO_RELEVANT_MEMORY")
    return 0




def cmd_memory(args) -> int:
    home = _home(args)
    if args.memory_command == "add":
        project_id = args.project_id
        if args.scope == "project" and project_id is None:
            # Reuse the authoritative project registry (root containing cwd);
            # never silently fall back to second-brain.
            project_id = _project_from_cwd(home)
            if project_id is None:
                print(
                    "memory add with scope=project requires --project "
                    "(no registered project root contains the working directory)"
                )
                return 2
        source_rows = _parse_sources(args.sources)
        for specification in getattr(args, "evidence", None) or []:
            captured = semantic.capture_evidence(Path.cwd(), specification)
            if source_rows is None:
                source_rows = []
            source_rows.append(captured)
        captured_root = next(
            (row.get("origin_root_sha") for row in source_rows or [] if row.get("origin_root_sha")),
            None,
        )
        mid = semantic.add_memory(
            home,
            args.title,
            args.body,
            scope=args.scope,
            project_id=project_id,
            grade=args.grade,
            sources=source_rows,
            origin_class="LOCAL_REPO" if captured_root else "MODEL_INFERENCE",
            origin_root_sha=captured_root,
        )
        print(f"Memory added: {mid} [{args.grade}/candidate]")
        return 0
    if args.memory_command == "curate":
        row = semantic.curate(
            home,
            args.memory_id,
            grade=args.grade,
            status=args.status,
            sources=_parse_sources(args.sources),
            verify=not args.no_verify,
            authority_ceiling=args.authority_ceiling,
        )
        print(f"{row['memory_id']} -> grade={row['evidence_grade']} status={row['status']}")
        return 0
    if args.memory_command == "list":
        rows = semantic.list_memories(
            home,
            scope=args.scope,
            project_id=args.project_id,
            status=args.status,
            grade=args.grade,
        )
        for r in rows:
            print(
                f"{r['memory_id']:20s} {r['evidence_grade']:10s} {r['status']:10s} "
                f"v{r['current_version']} {r['title'][:60]}"
            )
        return 0
    if args.memory_command == "show":
        m = semantic.show_memory(home, args.memory_id)
        print(
            f"id: {m['row']['memory_id']}  grade: {m['row']['evidence_grade']}  "
            f"status: {m['row']['status']}  v{m['row']['current_version']}"
        )
        print(m["body"])
        return 0
    if args.memory_command == "supersede":
        v = semantic.supersede(
            home,
            args.memory_id,
            new_title=args.new_title,
            new_body=args.new_body,
            change_note=args.change_note,
            new_sources=_parse_sources(args.new_sources),
        )
        print(f"{args.memory_id} -> v{v}")
        return 0
    if args.memory_command == "history":
        for v in semantic.history(home, args.memory_id):
            note = v.get("change_note") or "(current)"
            print(f"v{v['version']} {v['created_at']} {note}  path={v['body_path']}")
        return 0
    if args.memory_command == "contradictions":
        pairs = semantic.contradictions(home, scope=args.scope)
        if not pairs:
            print("No contradiction candidates.")
        for pair in pairs:
            print(f"{pair['memory_id_a']} <-> {pair['memory_id_b']}  (title {pair['title']!r})")
        return 0
    if args.memory_command == "search":
        rows = semantic.search_memories(
            home,
            args.term,
            project_id=args.project_id,
            include_history=args.history,
            include_duplicates=args.duplicates,
        )
        if not rows:
            print("No matching memories.")
        for row in rows:
            print(f"{row['memory_id']}  [{row['status']}/{row['evidence_grade']}] {row['title']}")
        conflicts = [r for r in rows if r.get("contradiction_with")]
        if conflicts:
            print()
            print("Conflicting prior evidence:")
            for row in conflicts:
                print(
                    f"  {row['memory_id']} <-> "
                    f"{', '.join(row['contradiction_with'])}  ({row['title']})"
                )
        return 0
    if args.memory_command == "reindex":
        counts = semantic.reindex_all(home)
        print(
            f"reindexed {counts['indexed']} (skipped {counts['skipped']} unchanged, "
            f"purged {counts['purged']} stale)"
        )
        return 0
    return 2


def cmd_metacog(args) -> int:
    import json

    home = _home(args)
    if args.metacog_command == "assess":
        capsule = working_set.show_capsule(home, args.session_id)
        requirements = working_set.show_requirements(home, args.session_id)
        reads = working_set.show_reads(home, args.session_id)
        telemetry_records = []
        if args.telemetry:
            try:
                telemetry_records = [
                    json.loads(line)
                    for line in Path(args.telemetry).read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    f"brainctl: error: cannot read telemetry {args.telemetry}: {exc}",
                    file=sys.stderr,
                )
                return 2
        git_info = {}
        if args.repo:
            from second_brain import scout as _scout

            prepass = _scout.deterministic_prepass(Path(args.repo), "")
            git_info = prepass.get("git") or {}
        result = monitor.assess_confidence(
            capsule, requirements, reads, telemetry_records, git_info
        )
        print(
            f"epistemic={result['epistemic']} execution={result['execution']} "
            f"verification={result['verification']}"
        )
        for s in result["signals"]:
            if s["strength"]:
                print(f"  {s['name']:24s} {s['strength']} ({s['effect']}) {s['detail']}")
        return 0
    if args.metacog_command == "eval":
        repo_root = Path(__file__).resolve().parent.parent.parent
        fixture = (
            Path(args.fixture)
            if args.fixture
            else repo_root / "tests" / "fixtures" / "trajectories.json"
        )
        data = json.loads(fixture.read_text(encoding="utf-8"))
        trajectories = data["trajectories"] if isinstance(data, dict) else data
        result = monitor.eval_monitor(trajectories)
        print(
            f"monitor={result['monitor_agreement']:.3f} "
            f"basic={result['basic_agreement']:.3f} random=0.5 n={result['n']}"
        )
        return 0
    return 2


def cmd_cerebellum(args) -> int:
    import json

    home = _home(args)
    if args.cerebellum_command == "assess":
        result = cerebellum.assess_workflow(home, args.session_id)
        print(f"progress: {result['progress']}")
        for s in result["signals"]:
            print(f"  {s['name']}: {s['detail']}")
        for e in result["events"]:
            print(f"  event: {e['rule']} expected={e['expected']} actual={e['actual']}")
        return 0
    if args.cerebellum_command == "eval":
        repo_root = Path(__file__).resolve().parent.parent.parent
        data = json.loads(
            (repo_root / "tests" / "fixtures" / "workflows.json").read_text(encoding="utf-8")
        )
        workflows = data["workflows"] if isinstance(data, dict) else data
        result = cerebellum.eval_cerebellum(workflows)
        print(
            f"cerebellum={result['cerebellum_agreement']:.3f} "
            f"fixed={result['fixed_agreement']:.3f} n={result['n']}"
        )
        for ed in result["early_detection"]:
            print(f"  {ed['label']}: cerebellum@{ed['cerebellum_read']} fixed@{ed['fixed_read']}")
        return 0
    return 2


def cmd_plasticity(args) -> int:
    import json

    home = _home(args)
    if args.plasticity_command == "predict":
        pid = plasticity.record_prediction(
            home, args.session_id, args.state, args.expected, args.actual, args.kind
        )
        print(f"Prediction {pid} recorded")
        return 0
    if args.plasticity_command == "outcome":
        vector: dict = {}
        for kv in args.kv:
            k, _, v = kv.partition("=")
            vector[k] = (
                json.loads(v)
                if v.startswith(("[", "{"))
                else (v if v not in ("true", "false", "null") else json.loads(v))
            )
        oid = plasticity.record_outcome(home, args.session_id, vector)
        print(f"Outcome {oid} recorded")
        return 0
    if args.plasticity_command == "credit":
        cid = plasticity.record_credit(
            home, args.session_id, args.subject_id, args.subject_kind, args.credit_level
        )
        print(f"Credit {cid} recorded ({args.credit_level})")
        return 0
    if args.plasticity_command == "hindsight":
        out = plasticity.hindsight_relabel(home, args.session_id, args.predicted, args.actual)
        print(
            f"hindsight: error={'yes' if out['error'] else 'no'} prediction={out['prediction_id']}"
        )
        return 0
    if args.plasticity_command == "utility":
        rec = plasticity.utility_update(
            home, args.subject_id, args.subject_kind, args.delta, args.evidence
        )
        print(f"utility delta appended ({rec['delta']:+g})")
        return 0
    return 2


def cmd_sleep(args) -> int:
    home = _home(args)
    if args.sleep_command == "queue":
        for e in sleep.replay_queue(home):
            print(f"{e['priority']:5.2f} {e['episode_id']:40s} {e['episode_type']}")
        return 0
    if args.sleep_command == "consolidate":
        result = sleep.consolidate(home, limit=args.limit, dry_run=not args.apply)
        print(f"queue={len(result['queue'])} clusters={len(result['clusters'])}")
        for c in result["clusters"]:
            print(f"  cluster: {', '.join(c['episode_ids'])}")
        for m in result["strengthened"]:
            print(
                f"  strengthened: {m['memory_id']} {m['strength_before']:.2f}->"
                f"{m['strength_after']:.2f} (+{len(m['sources_added'])} sources)"
                + (" (dry run)" if result.get("dry_run") else "")
            )
        print("  contradictions:", len(result["contradictions"]))
        print(f"report: {result['report_path']}")
        return 0
    return 2


def cmd_reconsolidation(args) -> int:
    home = _home(args)
    if args.reconsolidation_command == "retrieval":
        rid = reconsolidation.record_retrieval(home, args.memory_id, session_id=args.session_id)
        print(f"retrieval {rid} recorded")
        return 0
    if args.reconsolidation_command == "activation":
        aid = reconsolidation.record_activation(
            home, args.memory_id, args.outcome, session_id=args.session_id
        )
        print(f"activation {aid} recorded ({args.outcome})")
        return 0
    if args.reconsolidation_command == "heat":
        row = reconsolidation.apply_heat(home, args.memory_id, args.heat)
        print(f"{args.memory_id} heat -> {row['heat']}")
        return 0
    if args.reconsolidation_command == "decay":
        changes = reconsolidation.decay_pass(home, dry_run=not args.apply)
        print(f"{len(changes)} memories would decay" + ("" if args.apply else " (dry run)"))
        for c in changes:
            print(f"  {c['memory_id']} {c['heat_before']}->{c['heat_after']} {c['reason']}")
        return 0
    return 2


def cmd_skills(args) -> int:
    import json

    home = _home(args)
    if args.skills_command == "forge":
        path = skillforge.forge_candidate(home, args.name, args.episode_ids)
        print(f"Candidate forged: {path}")
        return 0
    if args.skills_command == "validate":
        result = skillforge.validate_candidate(home, args.name)
        print(f"ok={result['ok']}")
        for issue in result["issues"]:
            print(f"  - {issue}")
        return 0 if result["ok"] else 1
    if args.skills_command == "eval":
        repo_root = Path(__file__).resolve().parent.parent.parent
        cases_path = (
            Path(args.cases)
            if args.cases
            else repo_root / "tests" / "fixtures" / "skill-eval-cases.json"
        )
        data = json.loads(cases_path.read_text(encoding="utf-8"))
        trig = skillforge.trigger_eval(home, args.name, data["trigger_cases"])
        wf = skillforge.workflow_eval(home, args.name, data["workflow_scenarios"])
        reg = skillforge.regression_eval(home, args.name, data["regression_baselines"])
        sec = skillforge.security_review(home, args.name)
        print(
            f"trigger={trig['passed']}/{trig['total']} workflow={wf['structural']} "
            f"regression={'pass' if not reg['regression'] else 'fail'} "
            f"security={'pass' if sec['passed'] else 'fail'}"
        )
        for f in sec["findings"]:
            print(f"  security: {f}")
        return 0
    if args.skills_command == "shadow":
        repo_root = Path(__file__).resolve().parent.parent.parent
        cases_path = (
            Path(args.cases)
            if args.cases
            else repo_root / "tests" / "fixtures" / "skill-eval-cases.json"
        )
        data = json.loads(cases_path.read_text(encoding="utf-8"))
        path = skillforge.shadow_candidate(
            home,
            args.name,
            trigger_cases=data["trigger_cases"],
            baseline_cases=data["regression_baselines"],
        )
        print(f"Shadowed: {path}")
        return 0
    if args.skills_command == "audit":
        result = skillforge.audit_lifecycle(home)
        print(f"ok={result['ok']}")
        for issue in cast(list[str], result["issues"]):
            print(f"  - {issue}")
        return 0 if result["ok"] else 1
    if args.skills_command == "list":
        for c in skillforge.list_candidates(home):
            print(f"candidate {c}")
        for s in skillforge.list_shadow(home):
            print(f"shadow    {s}")
        return 0
    return 2


def cmd_router(args) -> int:
    import json

    home = _home(args)
    if args.router_command == "route":
        result = router.route(home, args.task, max_active=args.max_active)
        print(f"shadow route -> {result['selected'] or '(none)'}")
        for name, score in sorted(result["scores"].items(), key=lambda kv: -kv[1]):
            print(f"  {score:6.2f} {name}")
        return 0
    if args.router_command == "eval":
        repo_root = Path(__file__).resolve().parent.parent.parent
        data = json.loads(
            (repo_root / "tests" / "fixtures" / "router-tasks.json").read_text(encoding="utf-8")
        )
        tasks = data["tasks"] if isinstance(data, dict) else data
        result = router.eval_router(home, tasks)
        r_, n_ = result["router"], result["natural"]
        print(
            f"router: precision={r_['precision']:.3f} recall={r_['recall']:.3f} "
            f"f1={r_['f1']:.3f} noise={r_['noise']}"
        )
        print(
            f"natural: precision={n_['precision']:.3f} recall={n_['recall']:.3f} "
            f"f1={n_['f1']:.3f} noise={n_['noise']}"
        )
        return 0
    return 2


def cmd_credit(args) -> int:
    import json

    home = _home(args)
    if args.credit_command == "assign":
        counts = credit.assign_credit(
            home,
            args.session_id,
            direct=args.direct,
            contributory=args.contributory,
            correlated=args.correlated,
        )
        print(f"credit assigned: {counts}")
        return 0
    if args.credit_command == "report":
        rep = credit.credit_report(home, session_id=args.session_id)
        print(f"total_events={rep['total_events']}")
        for s in rep["subjects"]:
            print(
                f"  {s['subject_id']:30s} {s['subject_kind']:12s} "
                f"direct={s['direct']} contributory={s['contributory']} "
                f"correlated={s['correlated']}"
            )
        return 0
    if args.credit_command == "counterfactual":
        data = json.loads(Path(args.tasks_file).read_text(encoding="utf-8"))
        tasks = data["tasks"] if isinstance(data, dict) else data
        result = credit.routing_counterfactual(home, args.skill_name, tasks)
        print(
            f"affected={result['tasks_affected']} "
            f"unaffected={result['tasks_unaffected']} total={len(result['tasks'])}"
        )
        for t in result["results"]:
            print(
                f"  {t['text'][:60]!r}: with={t['selected_with']} without={t['selected_without']}"
            )
        return 0
    return 2

def cmd_optimize(args) -> int:
    import json

    home = _home(args)
    if args.optimization_command == "propose":
        result = optimization.propose(
            home,
            args.fingerprint_id,
            skill_name=args.skill_name,
            intervention_hash=args.intervention_hash,
            mode=args.mode,
        )
    elif args.optimization_command == "evaluate":
        try:
            result_data = json.loads(args.result_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrainError(f"invalid evaluation JSON: {args.result_json}") from exc
        result = optimization.evaluate(home, args.proposal_id, result_data)
    elif args.optimization_command == "activate":
        result = optimization.activate(home, args.proposal_id, session_id=args.session_id)
    elif args.optimization_command == "rollback":
        result = optimization.rollback(home, args.proposal_id, args.trigger_id, args.reason)
    elif args.optimization_command == "show":
        result = optimization.get_proposal(home, args.proposal_id)
    else:
        return 2

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    return 0


def cmd_promote(args) -> int:
    home = _home(args)
    result = promotion.promote(
        home, args.skill_name, args.from_level, args.to_level, session_id=args.session_id
    )
    print(f"promoted={result['promoted']} reason={result.get('reason', '')}")
    return 0 if result["promoted"] else 1


def cmd_demote(args) -> int:
    home = _home(args)
    result = promotion.demote(home, args.skill_name, args.to_level, args.reason)
    print(
        f"demoted={result.get('demoted', result.get('promoted', False))} "
        f"reason={result.get('reason', '')}"
    )
    return 0


def cmd_promotions(args) -> int:
    home = _home(args)
    status = promotion.promotion_status(home)
    print(status)
    return 0


def cmd_immune(args) -> int:
    home = _home(args)
    if args.immune_command == "policy":
        guard = {
            "rollback_trigger": args.rollback_trigger,
            "rollback_target": args.rollback_target,
            "backup_of": args.backup_of,
        }
        rec = immune.register_policy(home, args.policy_id, guard)
        print(f"policy registered: {rec['policy_id']}")
        return 0
    if args.immune_command == "trigger":
        matcher = {
            "metric": args.metric,
            "operator": args.operator,
            "value": args.value,
            "window": args.window,
        }
        rec = immune.register_trigger(home, args.trigger_id, matcher)
        print(f"trigger registered: {rec['trigger_id']}")
        return 0
    if args.immune_command == "ingest":
        immune.ingest_metric(home, args.metric, args.value, args.run_id)
        print(f"ingested {args.metric}={args.value}")
        return 0
    if args.immune_command == "check":
        for r in immune.check_triggers(home, policy_id=args.policy_id):
            print(
                f"{r['trigger_id']}: matched={r['matched']} computed={r['computed']} "
                f"policies={r['policy_ids']}"
            )
        return 0
    if args.immune_command == "rollback":
        result = immune.rollback(home, args.policy_id, args.trigger_id, args.reason)
        print(f"rolled_back={result['rolled_back']} reason={result.get('reason', '')}")
        return 0 if result["rolled_back"] else 1
    if args.immune_command == "log":
        for rec in immune.rollback_log(home):
            print(f"{rec.get('ts', '')} {rec.get('policy_id', '')}: {rec.get('reason', '')}")
        return 0
    return 2


def cmd_frontier(args) -> int:
    home = _home(args)
    if args.frontier_command == "review":
        path = frontier.frontier_review(
            home,
            args.change_id,
            args.summary,
            args.risk,
            args.reviewer,
            args.verdict,
            notes=args.notes,
        )
        print(f"review: {path}")
        return 0
    if args.frontier_command == "require":
        path = frontier.require_review(home, args.change_id, args.summary, risk=args.risk)
        print(f"hold: {path if path else 'HARD GATE (high risk, no review)'}")
        return 0
    if args.frontier_command == "gate":
        result = frontier.gate_check(home, args.change_id)
        print(f"ok={result['ok']} missing={result['missing']}")
        return 0 if result["ok"] else 1
    if args.frontier_command == "status":
        status = frontier.frontier_status(home, change_id=args.change_id)
        if args.change_id:
            print(
                f"{status['change_id']}: latest={status['latest_verdict']} "
                f"reviews={len(status['reviews'])}"
            )
        else:
            print(
                f"total={status['total']} approved={status['approved']} "
                f"rejected={status['rejected']} request_changes={status['request_changes']} "
                f"pending_high_risk={status['pending_high_risk']}"
            )
        return 0
    if args.frontier_command == "pending":
        for hold in frontier.list_pending(home):
            print(hold)
        return 0
    return 2


def cmd_models(args) -> int:
    home = _home(args)
    if args.models_command == "add":
        crossmodel.record_model(
            home, args.model_id, family=args.family, capabilities=args.capabilities
        )
        print(f"profile recorded: {args.model_id}")
        return 0
    if args.models_command == "record":
        oid = crossmodel.record_skill_outcome(
            home,
            args.model_id,
            args.skill_name,
            args.task,
            success=args.success,
            noise=args.noise,
            f1=args.f1,
            session_id=args.session_id,
        )
        print(f"outcome recorded: {oid}")
        return 0
    if args.models_command == "transfer":
        result = crossmodel.transfer_test(home, args.skill_name, args.model_a, args.model_b)
        print(f"verdict={result['verdict']} overlap={result['overlap_count']}")
        for d in result["tasks"]:
            print(f"  {d['task_hash']}: a={d['success_a']} b={d['success_b']}")
        return 0
    if args.models_command == "policy":
        stats = crossmodel.global_policy_stats(home, args.skill_name)
        print(
            f"included={stats['models_included']} excluded={stats['models_excluded']} "
            f"success_rate={stats['success_rate']:.3f}"
        )
        return 0
    if args.models_command == "report":
        rep = crossmodel.model_skill_report(home)
        for m in rep["models"]:
            print(
                f"  {m['model_id']:20s} outcomes={m['outcomes']} successes={m['successes']} "
                f"f1={m['f1_mean']:.3f} noise={m['noise_mean']:.2f}"
            )
        return 0
    return 2


def cmd_engrams(args) -> int:
    import json

    home = _home(args)
    if args.engrams_command == "detect":
        data = json.loads(Path(args.sequences_file).read_text(encoding="utf-8"))
        sequences = data["sequences"] if isinstance(data, dict) else data
        for e in engram.detect_engrams(sequences, min_support=args.min_support):
            print(f"support={e['support']} len={len(e['sequence'])} {' -> '.join(e['sequence'])}")
        return 0
    if args.engrams_command == "write":
        path = engram.write_engram(
            home, args.name, args.skills, [[]], trigger_note=args.trigger_note
        )
        print(f"Engram candidate: {path}")
        return 0
    if args.engrams_command == "validate":
        result = engram.validate_engram(home, args.name)
        print(f"ok={result['ok']}")
        for i in result["issues"]:
            print(f"  - {i}")
        return 0 if result["ok"] else 1
    if args.engrams_command == "list":
        for e in engram.list_engrams(home):
            print(e)
        return 0
    return 2


def cmd_scout(args) -> int:
    import json

    home = _home(args)
    out_dir = Path(args.output) if args.output else None
    if args.no_agent:
        repo = scout.resolve_repo(home, args.target)
        prepass = scout.deterministic_prepass(repo, args.task)
        output_dir = out_dir or (home / "outputs" / "evidence-maps")
        map_path = scout.write_evidence_map(repo, args.task, prepass, output_dir)
        result = {"map_path": str(map_path), "prepass": prepass}
    else:
        result = scout.run_scout(
            home,
            args.target,
            args.task,
            model=args.model,
            out_dir=out_dir,
            ext=args.ext,
        )
    print(f"Evidence map: {result['map_path']}")
    if "rc" in result:
        print(f"agent rc: {result['rc']}")
        print((result.get("stdout_tail") or "").strip()[-400:])
    else:
        print("pre-pass only (no agent run)")
    print(json.dumps(result["prepass"], indent=1, default=str))
    return 0 if result.get("rc", 0) == 0 else 1


def cmd_capsule(args) -> int:
    import json

    home = _home(args)
    if args.capsule_command == "ensure":
        result = capsule_runtime.ensure_capsule(
            home,
            args.session_id,
            objective=args.objective,
            next_action=args.next_action,
            task_mode=args.task_mode,
            risk=args.risk,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"Capsule {'created' if result['changed'] else 'bound'}: "
                f"{result['capsule_path']}"
            )
        return 0
    if args.capsule_command == "init":
        path = working_set.init_capsule(
            home,
            args.session_id,
            args.objective,
            task_mode=args.task_mode,
            risk=args.risk,
            constraints=args.constraint or [],
        )
        print(f"Capsule created: {path}")
        return 0
    if args.capsule_command == "update":
        verification = None
        if args.verification_json is not None:
            try:
                verification = json.loads(args.verification_json)
            except json.JSONDecodeError as exc:
                print(f"brainctl: error: invalid verification JSON: {exc}", file=sys.stderr)
                return 2
            if not isinstance(verification, dict):
                print("brainctl: error: verification JSON must be an object", file=sys.stderr)
                return 2
        result = capsule_runtime.update_capsule(
            home,
            args.session_id,
            objective=args.objective,
            next_action=args.next_action,
            task_mode=args.task_mode,
            risk=args.risk,
            constraints=args.constraints,
            facts=args.confirmed_facts,
            hypotheses=args.current_hypotheses,
            decisions=args.decisions_this_session,
            files_touched=args.files_touched,
            open_questions=args.open_questions,
            brain_refs=args.brain_refs,
            artifact_refs=args.artifact_refs,
            verification=verification,
        )
        if not result["changed"] and not any(
            getattr(args, name, None) is not None
            for name in (
                "objective",
                "next_action",
                "task_mode",
                "risk",
                "constraints",
                "confirmed_facts",
                "current_hypotheses",
                "decisions_this_session",
                "files_touched",
                "open_questions",

                "brain_refs",
                "artifact_refs",
                "verification_json",
            )
        ):
            print("brainctl: error: no update fields given", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Capsule updated." if result["changed"] else "Capsule unchanged.")
        return 0
    if args.capsule_command == "show":
        print(json.dumps(working_set.show_capsule(home, args.session_id), indent=2))
        return 0
    return 2
def cmd_simplification(args) -> int:
    import json

    if args.simplification_command != "review":
        return 2
    metrics: dict[str, int | float] = {}
    for raw in args.metric:
        if "=" not in raw:
            raise BrainError(f"invalid metric {raw!r}; expected key=value")
        key, value = raw.split("=", 1)
        try:
            metrics[key] = float(value) if "." in value else int(value)
        except ValueError as exc:
            raise BrainError(f"invalid metric {raw!r}") from exc
    review = simplification.SimplificationReview(
        review_id=args.review_id,
        project_id=args.project_id,
        task_id=args.task_id,
        session_id=args.session_id,
        outcome=simplification.SimplificationOutcome(args.outcome),
        reason_code=args.reason_code,
        affected_hashes=args.affected_hash,
        changed_hashes=args.changed_hash,
        deferred_hashes=args.deferred_hash,
        debt_ref=args.debt_ref,
        verification=args.verification,
        metrics=metrics,
    )
    result = simplification.record_review(_home(args), args.project_root, review)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['outcome']} review {result['review_id']} recorded")
    return 0



def cmd_requirements(args) -> int:
    home = _home(args)
    if args.requirements_command == "add":
        entry = working_set.add_requirement(
            home,
            args.session_id,
            args.requirement,
            req_id=args.req_id,
            importance=args.importance,
        )
        print(
            f"Added {entry['id']} [{entry['importance']}/{entry['status']}]: {entry['requirement']}"
        )
        return 0
    if args.requirements_command == "evidence":
        entry = working_set.add_evidence(home, args.session_id, args.req_id, args.evidence)
        print(f"Evidence added to {entry['id']} ({len(entry['evidence'])} items)")
        return 0
    if args.requirements_command == "status":
        entry = working_set.set_requirement_status(home, args.session_id, args.req_id, args.status)
        print(f"{entry['id']} -> {entry['status']}")
        return 0
    if args.requirements_command == "show":
        for entry in working_set.show_requirements(home, args.session_id):
            print(
                f"{entry['id']:10s} {entry['importance']:10s} {entry['status']:20s} "
                f"{entry['requirement']}"
            )
            for ev in entry["evidence"]:
                print(f"    - evidence: {ev}")
        return 0
    if args.requirements_command == "check":
        result = working_set.check_requirements(home, args.session_id)
        print(
            f"{result['material_unverified']}/{result['material_total']} material "
            f"requirements unverified (gate {'on' if result['gate'] else 'off'})"
        )
        for entry in result["entries"]:
            print(
                f"  {entry['id']} [{entry['importance']}/{entry['status']}]: {entry['requirement']}"
            )
        return 1 if result["blocks"] else 0
    return 2


def cmd_handoff(args) -> int:
    """Brain Handoff Envelope CLI: bounded, harness-neutral transfer (P3.17)."""
    import json

    home = _home(args)
    if args.handoff_command == "create":
        envelope, artifact = handoff.create_handoff_envelope(
            home,
            args.session_id,
            source_harness=args.source_harness,
            target_harness=args.target_harness,
            target_role=args.target_role,
            source_task_id=args.source_task_id,
            source_role=args.source_role,
            project_id=args.project_id,
            context_refs=args.context_refs,
            artifact_refs=args.artifact_refs,
            evidence_refs=args.evidence_refs,
            unavailable_evidence=args.unavailable_evidence,
        )
        if args.json:
            print(json.dumps({
                "envelope": envelope.to_dict(),
                "markdown_path": artifact.artifact_path,
                "envelope_bytes": envelope.envelope_bytes(),
            }, indent=2, default=str))
        else:
            print(f"Handoff created: {envelope.handoff_id}")
            print(f"  envelope ref: {artifact.envelope_ref}")
            print(f"  markdown:     {artifact.artifact_path}")
            print(f"  bytes:        {envelope.envelope_bytes()}")
        return 0
    if args.handoff_command == "read":
        data = json.loads(args.envelope_path.read_text(encoding="utf-8"))
        recovered = handoff.read_handoff_envelope(
            home, data, expected_project_id=args.project_id, allow_stale=args.allow_stale
        )
        print(json.dumps(recovered, indent=2, default=str))
        return 0
    return 2


def cmd_read_ledger(args) -> int:
    home = _home(args)
    if args.read_ledger_command == "record":
        entry = working_set.record_read(
            home,
            args.session_id,
            args.path,
            purpose=args.purpose,
            turn=args.turn,
            range_text=args.range_text,
            artifact=args.artifact,
            distilled_ref=args.distilled_ref,
        )
        hash_part = f" (hash {entry['hash'][:12]}...)" if entry.get("hash") else " (file missing)"
        print(f"Recorded read: {entry['path']}{hash_part}")
        return 0
    if args.read_ledger_command == "show":
        entries = working_set.show_reads(home, args.session_id)
        for e in entries:
            extra = f" turn={e['turn']}" if e.get("turn") is not None else ""
            print(f"{e['ts']} {e['path']}{extra} — {e['purpose']}")
        if not entries:
            print("(no reads recorded)")
        return 0
    return 2

def cmd_working_set(args) -> int:
    import json
    from . import autoinject, decisions

    if args.working_set_command != "reread-hint":
        return 2
    home = _home(args)
    if args.mode == "OFF":
        print("null")
        return 0
    hint = working_set.reread_hint(home, args.session_id, args.path)
    if hint is not None:
        try:
            path_sha = hashlib.sha256(Path(args.path).read_bytes()).hexdigest()
            decisions.record(
                home,
                kind="reread",
                session_id=args.session_id,
                task_id=args.tool_call_id,
                chosen={"action": "reread_avoidable"},
                alternatives={"mode": args.mode},
                propensity=1.0,
                randomized=False,
                policy_version="reread-1",
                stage=args.mode,
                inputs={"path_sha256": path_sha},
            )
            autoinject._append_telemetry(
                home,
                args.session_id,
                "reread_avoidable",
                {"tool": args.tool, "path_sha256": path_sha},
            )
        except (OSError, BrainError):
            pass
    print(json.dumps(hint, sort_keys=True))
    return 0


def cmd_context(args) -> int:
    home = _home(args)
    if args.context_command == "compile":
        path = jit_mod.compile_context(
            home, args.session_id, args.task, project_key=args.project_key
        )
        print(f"Context capsule: {path}")
        return 0
    return 2


# Backward-compatible private aliases for the pre-existing white-box test
# suite (tests/test_antigravity_adapter.py, tests/test_claude_code_adapter.py,
# tests/test_lean_canary.py, tests/test_ledger.py), which call these hook
# entry points and helpers as `cli._name(...)` directly. The real
# implementations now live in `second_brain.adapters.*`; do not add new
# call sites against these aliases.
from .adapters import antigravity as _antigravity_adapter
from .adapters import claude_code as _claude_code_adapter
from .adapters import codex as _codex_adapter

_cmd_codex_shadow = _codex_adapter.run
_cmd_antigravity_hook = _antigravity_adapter.run
_cmd_claude_code_hook = _claude_code_adapter.run
_claude_usage_records = _claude_code_adapter._claude_usage_records
_claude_tool_call_args = antigravity_transcript.extract_tool_call_args


def _cmd_hermes_hook(home: Path) -> int:
    """Hermes plugin bridge over the existing Brain primitives.

    The Hermes plugin is intentionally transport-only: it sends one bounded
    JSON request to this command and receives one JSON response. Policy,
    identity mapping, AutoInject, writeback, telemetry, and ledger operations
    remain in the Brain adapter.
    """
    import json

    from . import contracts, hermes_adapter

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:
        payload = None
    response = hermes_adapter.handle_request(home, payload)
    print(contracts.canonical_json(response))
    return 0

def _cmd_omp_routing(home: Path) -> int:
    """OMP transport bridge; Brain owns all routing policy and selection."""
    import json

    from . import contracts, omp_adapter

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:
        payload = None
    response = omp_adapter.handle_request(home, payload)
    print(contracts.canonical_json(response))
    return 0


def _cmd_writeback(home: Path, args) -> int:
    """P0-G9 write-back: outcome candidate creation (fail-open JSON output)."""
    import json

    from . import autoinject, contracts

    try:
        evidence = json.loads(args.evidence) if args.evidence.strip() else []
        if isinstance(evidence, dict):
            # T-G6-F4: plain dict {ref: kind, ...} normalizes to the canonical
            # list schema [{ref, kind}, ...]
            evidence = [
                {"ref": str(ref), "kind": str(kind) if isinstance(kind, str) else "evidence"}
                for ref, kind in evidence.items()
            ]
        if not isinstance(evidence, list):
            raise ValueError("--evidence must be a JSON list of {ref, kind} dicts or a dict")
        session = contracts.BrainSessionIdentity(
            internal_session_id=ledger.internal_session_id(args.session_id),
            host="brainctl",
            host_session_id=args.session_id,
            project_id=args.project_id,
            created_at=datetime.now(UTC).isoformat(),
            status="active",
            pinned=False,
            schema_version=1,
        )
        lifecycle = autoinject.BrainLifecycle(home, session)
        memory_id = lifecycle.writeback_candidate(
            session_id=args.session_id,
            project_id=args.project_id,
            title=args.title,
            observation=args.observation,
            guidance=args.guidance,
            evidence=evidence,
        )
        print(
            contracts.canonical_json(
                {
                    "memory_id": memory_id,
                    "status": "candidate",
                    "session_id": args.session_id,
                    "project_id": args.project_id,
                }
            )
        )
    except Exception as exc:  # fail-open: report, never crash the CLI
        print(contracts.canonical_json({"error": str(exc), "status": "error"}))
    return 0


_ORCH_COUNTER_KEYS = (
    "driver_actions_total",
    "driver_execution_attempts",
    "blocked_execution_attempts",
    "emergency_execution_actions",
    "worker_tasks",
    "worker_corrections",
    "worker_verifications",
    "fan_out_width",
    "recursion_depth",
)


def cmd_orchestration(args) -> int:
    """P1 orchestration telemetry (plan §19/20 purity; amendment §12/§22).

    `orchestration record --json-stdin`: reads ONE JSON event with the nine
    counter fields, computes delegation_purity, appends a privacy-safe JSONL
    record to telemetry/agent-performance/orchestration-<session>.jsonl.
    Fail-open: malformed/missing/invalid input -> {"recorded": false,
    "error": ...} with exit 0; only the nine counters are ever persisted
    (no secrets, no arbitrary payload).
    """
    import json

    from . import contracts
    from . import telemetry as telemetry_mod

    home = _home(args)
    if args.orchestration_command != "record":
        return 2
    payload = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:  # fail-open
        payload = None
    session = args.session or (
        str(payload.get("session"))
        if isinstance(payload, dict) and payload.get("session")
        else "unknown"
    )
    if not isinstance(payload, dict):
        print(contracts.canonical_json({"recorded": False, "error": "expected one JSON object"}))
        return 0
    counters: dict[str, int] = {}
    for key in _ORCH_COUNTER_KEYS:
        value = payload.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            print(
                contracts.canonical_json(
                    {"recorded": False, "error": f"{key} must be a non-negative int"}
                )
            )
            return 0
        counters[key] = value
    total = counters["driver_actions_total"]
    if total > 0:
        purity = 1.0 - (
            counters["driver_execution_attempts"] + counters["emergency_execution_actions"]
        ) / total
        purity = round(purity, 6)
    else:
        purity = None  # no actions recorded -> not inferred, never fabricate
    record = {
        "v": 2,
        "ts": datetime.now(UTC).isoformat(),
        "kind": "orchestration_record",
        "session": session,
        "delegation_purity": purity,
        **counters,
    }
    try:
        tdir = telemetry_mod.telemetry_dir(home)
        tdir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9_-]", "-", session) or "unknown"
        with open(tdir / f"orchestration-{stem}.jsonl", "a", encoding="utf-8") as f:
            f.write(contracts.canonical_json(record) + "\n")
    except Exception as exc:  # fail-open
        print(contracts.canonical_json({"recorded": False, "error": str(exc)}))
        return 0
    print(
        contracts.canonical_json(
            {"recorded": True, "delegation_purity": purity, "session": session}
        )
    )
    return 0


def cmd_ledger(args) -> int:
    """P2 session ledger CLI (plan §9/§9.10/§14)."""
    import json as _json

    from . import autoinject, contracts, ledger

    home = _home(args)
    cmd = args.ledger_command
    if cmd == "init":
        artifacts: list[dict[str, str]] = []
        for spec in args.host_artifacts:
            kind, _, path = spec.partition("=")
            if not kind or not path:
                print(
                    contracts.canonical_json(
                        {"error": f"bad --host-artifact {spec!r} (KIND=PATH)"}
                    )
                )
                return 2
            artifacts.append({"kind": kind, "path": path})
        # Project attribution: when --cwd is supplied, resolve project_id
        # through the SAME ladder AutoInject uses (autoinject._resolve_project_id,
        # src/second_brain/autoinject.py:157-193): explicit --project > registry
        # root containing cwd > SECOND_BRAIN_PROJECT env > 'default'. With no
        # --cwd, keep the historical behavior ('' unless --project given) so
        # existing callers are unchanged.
        project_id = (
            autoinject._resolve_project_id(home, args.cwd, args.project_id)
            if args.cwd
            else (args.project_id or "")
        )
        store = ledger.LedgerStore(home, args.host_session_id, host=args.host)
        store._init_host_artifacts = artifacts  # carried into the manifest at open
        with store.open(create=True):
            internal = ledger.internal_session_id(args.host_session_id)
            store.create_session(
                contracts.BrainSessionIdentity(
                    internal_session_id=internal,
                    host=args.host,
                    host_session_id=args.host_session_id,
                    project_id=project_id,
                    created_at=datetime.now(UTC).isoformat(),
                    status="active",
                    pinned=False,
                    schema_version=contracts.LEDGER_SCHEMA_VERSION,
                )
            )
        print(contracts.canonical_json({"initialized": internal, "schema_version": 1}))
        return 0
    if cmd == "append":
        if not args.stdin_json:
            print(contracts.canonical_json({"error": "--stdin-json required"}))
            return 2
        try:
            raw = sys.stdin.read()
            data = _json.loads(raw) if raw.strip() else None
        except Exception:
            data = None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            print(contracts.canonical_json({"error": "expected one event object or an array"}))
            return 0
        events: list[contracts.BrainLifecycleEvent] = []
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            for item in data:
                if not isinstance(item, dict):
                    print(contracts.canonical_json({"error": "event entries must be objects"}))
                    return 0
                # T-G6-F1: seq<=0 makes append_events assign the authoritative
                # contiguous seq INSIDE its BEGIN IMMEDIATE transaction. The CLI
                # must NOT pre-assign seqs here: a stale read outside the
                # transaction races with concurrent appends (each mirror event
                # spawns its own process) and skipped unknown-ignorable events
                # would consume counter slots, both poisoning contiguity.
                if (
                    "seq" not in item
                    or not isinstance(item.get("seq"), int)
                    or int(item.get("seq", 0)) <= 0
                ):
                    item["seq"] = 0  # ledger assigns; durable ledger is sequence authority
                # host mirrors are stateless: the ledger derives its own ids
                if not item.get("internal_session_id"):
                    item["internal_session_id"] = ledger.internal_session_id(
                        args.host_session_id
                    )
                if not item.get("agent_id"):
                    item["agent_id"] = "unknown"
                parsed = contracts.BrainLifecycleEvent.from_dict(item)
                if parsed is None:
                    continue  # unknown + ignorable -> skip
                events.append(parsed)
                if parsed.event_type is contracts.LifecycleEventType.SESSION_STARTED:
                    payload = parsed.payload or {}
                    if payload.get("agent_id"):
                        store.register_agent(
                            {
                                "agent_id": str(payload["agent_id"]),
                                "internal_session_id": parsed.internal_session_id,
                                "host_agent_id": str(
                                payload.get("host_agent_id") or payload["agent_id"]
                            ),
                                "parent_agent_id": payload.get("parent_agent_id"),
                                "role_profile": str(payload.get("role_profile") or "worker"),
                                "model": str(payload.get("model") or "unknown"),
                                "provider": str(payload.get("provider") or "unknown"),
                                "created_at": parsed.timestamp,
                            }
                        )
            seqs = store.append_events(events)
        print(contracts.canonical_json({"appended": seqs}))
        return 0
    if cmd == "verify":
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            integrity = store.integrity()
            lineage = args.lineage.split(",") if args.lineage else []
            replay_error = ""
            try:
                projection = store.replay(lineage)
                replay_ok = True
            except BrainError as exc:
                replay_ok = False
                projection = None
                replay_error = str(exc)
        out = {
            "integrity": integrity,
            "replay_ok": replay_ok,
            "events": len(projection.events) if projection else 0,
        }
        if not replay_ok:
            out["replay_error"] = replay_error
        print(contracts.canonical_json(out))
        return 0 if replay_ok else 1
    if cmd == "reindex":
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            result = store.reindex()
        print(contracts.canonical_json(result))
        return 0
    if cmd == "search":
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            rows = store.search(
                args.query,
                segment=args.segment,
                agent=args.agent,
                event_type=args.event_type,
            )
        print(contracts.canonical_json({"hits": rows}))
        return 0
    if cmd == "segment":
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            if args.segment_command == "open":
                segment_id = store.open_segment(args.reason)
                print(contracts.canonical_json({"opened": segment_id, "reason": args.reason}))
                return 0
            if args.segment_command == "close":
                closed = store.close_segment()
                print(contracts.canonical_json({"closed": closed}))
                return 0
            if args.segment_command == "checkpoint":
                result = ledger.checkpoint_ledger(store)
                print(contracts.canonical_json(result))
                return 0 if result["ok"] else 1
        return 2
    if cmd == "rehydrate":
        with ledger.LedgerStore(home, args.host_session_id).open() as store:
            out = ledger.LedgerRehydrator(store).rehydrate(
                args.level,
                segment=args.segment,
                decision=args.decision,
                from_seq=args.from_seq,
                to_seq=args.to_seq,
            )
        print(contracts.canonical_json(out))
        return 0
    return 2
def cmd_stop(args) -> int:
    """P3.6 STOP decision using the existing requirement ledger and ledger store."""
    from . import contracts, ledger

    home = _home(args)
    import json

    check = working_set.check_requirements(home, args.host_session_id)
    gate: dict[str, object] | None = None
    if args.gate_file is not None:
        try:
            parsed_gate = json.loads(args.gate_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrainError(f"invalid accuracy gate file: {args.gate_file}") from exc
        if not isinstance(parsed_gate, dict) or not isinstance(
            parsed_gate.get("completion_allowed"), bool
        ):
            raise BrainError(f"invalid accuracy gate file: {args.gate_file}")
        gate = parsed_gate
    gate_blocked = gate is not None and gate["completion_allowed"] is False
    gate_parent_session = str(gate.get("parent_session_id") or "") if gate else ""
    gate_worker_session = str(gate.get("worker_session_id") or "") if gate else ""
    verification_state = args.verification_state
    completion_state = args.completion_condition_state
    if check["blocks"]:
        decision = "continue"
        reason_code = "requirements_unresolved"
    elif verification_state in {"failed", "blocked"} or completion_state in {"failed", "blocked"}:
        decision = "stop"
        reason_code = args.reason_code
    elif gate_blocked:
        decision = "continue"
        reason_code = "accuracy_gate_blocked"
    elif verification_state == "passed" and completion_state == "satisfied":
        decision = "stop"
        reason_code = args.reason_code
    else:
        decision = "continue"
        reason_code = (
            "verification_unresolved"
            if verification_state != "passed"
            else "completion_condition_unresolved"
        )
    continuation_forbidden = decision == "stop"
    payload = {
        "stop_id": args.stop_id,
        "task_id": args.task_id,
        "session_id": args.host_session_id,
        "parent_session_id": args.parent_session_id or gate_parent_session,
        "worker_session_id": args.worker_session_id or gate_worker_session,
        "decision": decision,
        "reason_code": reason_code,
        "triggering_condition": args.triggering_condition,
        "verification_state": verification_state,
        "completion_condition_state": completion_state,
        "final_substantive_event": args.final_substantive_event,
        "material_total": check["material_total"],
        "material_unverified": check["material_unverified"],
        "continuation_forbidden": continuation_forbidden,
        "accuracy_gate_id": gate.get("accuracy_gate_id") if gate else None,
        "gate_risk_level": gate.get("risk_level") if gate else None,
        "gate_ladder_id": gate.get("ladder_id") if gate else None,
        "gate_completion_allowed": gate.get("completion_allowed") if gate else None,
        "gate_decision_reason": gate.get("decision_reason") if gate else None,
    }
    event = contracts.BrainLifecycleEvent(
        seq=0,
        event_id=f"stop-{args.stop_id}",
        internal_session_id=ledger.internal_session_id(args.host_session_id),
        agent_id=args.worker_session_id or args.host_session_id,
        event_type=contracts.LifecycleEventType.STOP_DECIDED,
        timestamp=datetime.now(UTC).isoformat(),
        surface_visibility=contracts.SurfaceVisibility.RAW_ONLY,
        ignorable=False,
        payload=payload,
    )
    with ledger.LedgerStore(home, args.host_session_id, host="prime").open(create=True) as store:
        store.create_session(
            contracts.BrainSessionIdentity(
                internal_session_id=ledger.internal_session_id(args.host_session_id),
                host="prime",
                host_session_id=args.host_session_id,
                project_id="",
                created_at=event.timestamp,
                status="active",
                pinned=False,
                schema_version=contracts.LEDGER_SCHEMA_VERSION,
            )
        )
        seq = store.append_events([event])[0]
    payload = {**payload, "sequence": seq}
    if args.json:
        print(contracts.canonical_json(payload))
    else:
        print(f"{decision}: {reason_code}")
    return 0




def cmd_session(args) -> int:
    """P2 session lifecycle CLI (plan §12/§13; Phase G/T-G5)."""
    from . import contracts, ledger

    home = _home(args)
    cmd = args.session_command
    if cmd == "list":
        sessions = ledger.list_sessions(home)
        if args.json:
            print(contracts.canonical_json({"sessions": sessions}))
        else:
            for s in sessions:
                flag = "P" if s.get("pinned") else " "
                purged = " [PURGED]" if s.get("purged") else ""
                print(
                    f"{flag} {s.get('host_session_id')} {s.get('status')} "
                    f"{s.get('created_at') or ''}{purged}"
                )
        return 0
    if cmd == "pin":
        life = ledger.SessionLifecycle(home, args.host_session_id)
        life.pin(not args.unpin)
        print(contracts.canonical_json({"pinned": not args.unpin, "session": args.host_session_id}))
        return 0
    if cmd == "recover":
        life = ledger.SessionLifecycle(home, args.host_session_id)
        report = life.recover_report()
        print(contracts.canonical_json(report))
        return 0
    if cmd == "purge":
        host = args.host_session_id
        if args.oldest:
            host = ledger.select_oldest_inactive_unpinned(home)
            if host is None:
                print(contracts.canonical_json({"error": "no inactive unpinned session"}))
                return 0
        if host is None:
            print(contracts.canonical_json({"error": "host_session_id required (or --oldest)"}))
            return 2
        try:
            result = ledger.SessionLifecycle(home, host).purge(
                inactive=args.inactive,
                dry_run=args.dry_run,
                retention=ledger.load_retention_config(home),
            )
        except ledger.SessionLifecycleError as exc:
            print(contracts.canonical_json({"error": str(exc), "purged": False}))
            return 0  # fail-open: report, never crash
        print(contracts.canonical_json(result))
        return 0
    return 2


def cmd_autoinject(args) -> int:
    from . import autoinject, contracts

    home = _home(args)
    if args.autoinject_command == "codex-shadow":
        from .adapters import codex as codex_adapter

        return codex_adapter.run(home)
    if args.autoinject_command == "antigravity-hook":
        from .adapters import antigravity as antigravity_adapter

        return antigravity_adapter.run(home)
    if args.autoinject_command == "claude-code-hook":
        from .adapters import claude_code as claude_code_adapter

        return claude_code_adapter.run(home)
    if args.autoinject_command == "hermes-hook":
        return _cmd_hermes_hook(home)
    if args.autoinject_command == "omp-routing":
        return _cmd_omp_routing(home)
    if args.autoinject_command == "writeback":
        return _cmd_writeback(home, args)
    if args.autoinject_command != "shadow":
        return 2
    resolved_project = autoinject._resolve_project_id(home, args.cwd, args.project_id)
    session = contracts.BrainSessionIdentity(
        internal_session_id=ledger.internal_session_id(args.session_id),
        host="prime-cli",
        host_session_id=args.session_id,
        project_id=resolved_project,
        created_at=datetime.now(UTC).isoformat(),
        status="active",
        pinned=False,
        schema_version=1,
    )
    lifecycle = autoinject.BrainLifecycle(home, session)
    decision = lifecycle.prepare_injection(
        args.task,
        project_id=args.project_id,
        agent_id=args.agent_id,
        role_profile=args.role_profile,
        session_id=args.session_id,
        branch_id=args.branch,
        cwd=args.cwd,
    )
    packet = autoinject.render_packet(decision)
    delivery_id = lifecycle.last_delivery_ids[0] if lifecycle.last_delivery_ids else None
    if args.json:
        print(contracts.canonical_json(autoinject.shadow_output(decision, packet, delivery_id)))
    else:
        print(f"decision: {decision.decision.value}")
        print(f"reason: {decision.reason.value if decision.reason is not None else 'n/a'}")
        print(f"selected: {', '.join(decision.selected_ids) or 'none'}")
        print(f"delivery: {delivery_id or 'none'}")
    return 0
def cmd_heartbeat(args) -> int:
    import json

    from . import heartbeat, telemetry, worker_protocol

    home = _home(args)
    result = heartbeat.HeartbeatCoordinator(home).run_if_due(
        args.event,
        args.session_id,
        args.repo,
        force=args.force,
    )
    # Worker lease maintenance rides the same zero-token pulse as heartbeat.
    with contextlib.suppress(Exception):
        result["worker_reaped"] = worker_protocol.reap(home)
    with contextlib.suppress(OSError, ValueError):
        telemetry.append_record(
            home,
            args.session_id,
            "heartbeat_pulse",
            {
                "mode": result["mode"],
                "event": result["event"],
                "due": result["due"],
                "ran": result["ran"],
                "healthy": result["healthy"],
                "db_ok": result["db_ok"],
                "cache_pruned_count": result["cache_pruned_count"],
                "git_dirty": result["git_dirty"],
                "issue_codes": result["issue_codes"],
                "latency_ms": result["latency_ms"],
                "model_tokens_used": result["model_tokens_used"],
                "artifacts_gc_count": result["artifacts_gc_count"],
            },
        )
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0

def cmd_p4(args) -> int:
    import json

    from . import p4, worker_protocol

    home = _home(args)
    result = p4.pulse(
        home,
        event=args.event,
        session_id=args.session_id,
        repo_dir=args.repo,
        project_id=args.project_id,
        force=args.force,
        emit_telemetry=args.emit_telemetry,
    )
    # Prime invokes this command for session_start/turn_start. Reaping is
    # local and fail-open just like the surrounding P4 bridge.
    with contextlib.suppress(Exception):
        result["worker_reaped"] = worker_protocol.reap(home)
    if args.json:
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    else:
        print(result)
    return 0




def cmd_telemetry(args) -> int:
    import json

    from . import telemetry

    home = _home(args)
    if args.telemetry_command == "report":
        rep = telemetry.report(home, since=args.since)
        if args.as_json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            print(telemetry.format_report(rep))
        return 0
    if args.telemetry_command == "validate":
        result = telemetry.validate(home)
        print(
            f"{result['files']} files, {result['records']} records, {len(result['issues'])} issues"
        )
        for issue in result["issues"]:
            print(f"  {issue}")
        return 1 if result["issues"] else 0
    return 2





def cmd_calibrate(args) -> int:
    home = _home(args)
    if args.calibrate_command != "tokens":
        return 2
    # Keep the in-process estimator pointed at the same explicit CLI home.
    os.environ["SECOND_BRAIN_HOME"] = str(home)
    state = contracts.calibrate_tokens(home)
    if args.as_json:
        print(json.dumps(state, sort_keys=True))
    else:
        print(
            f"Token calibration: {state['source']} "
            f"({state['pair_count']} measured pair(s)); "
            f"state={home / 'state' / 'calibration' / 'tokens.json'}"
        )
    return 0

def cmd_governor(args) -> int:
    """Token Governor CLI: report, flags, compare."""
    import fnmatch
    import json

    home = _home(args)

    if args.governor_command == "report":
        # Parse all sessions
        sessions = governor.parse_telemetry(home)

        # Filter by session ID if requested
        if args.session:
            sessions = [s for s in sessions if s.session_id == args.session]

        if args.json:
            # Output as JSON array of SessionTokens dicts
            output = []
            for session in sessions:
                d = {
                    'session_id': session.session_id,
                    'provider': session.provider,
                    'model': session.model,
                    'input_tokens': session.input_tokens,
                    'output_tokens': session.output_tokens,
                    'cache_read_tokens': session.cache_read_tokens,
                    'cache_write_tokens': session.cache_write_tokens,
                    'total_tokens': session.total_tokens,
                    'cost_total': session.cost_total,
                    'cost_total_seen': session.cost_total_seen,
                    'context_peak': session.context_peak,
                    'model_turns': session.model_turns,
                    'tool_calls': session.tool_calls,
                    'tool_input_bytes': session.tool_input_bytes,
                    'tool_output_bytes': session.tool_output_bytes,
                    'brain_injected_tokens': session.brain_injected_tokens,
                    'brain_packets_delivered': session.brain_packets_delivered,
                    'brain_packets_shadow': session.brain_packets_shadow,
                    'autoinject_cache_hits': session.autoinject_cache_hits,
                    'autoinject_cache_misses': session.autoinject_cache_misses,
                    'autoinject_cache_hit_rate': session.autoinject_cache_hit_rate,
                    'lean_kernel_dedup_hits': session.lean_kernel_dedup_hits,
                    'compactions': session.compactions,
                    'role': session.role,
                    'cache_epochs': session.cache_epochs,
                }
                output.append(d)
            print(json.dumps(output, indent=2, default=str))
        else:
            # Table output
            print(
                f"{'Session':<16} {'Provider':<10} {'Model':<20} {'Turns':<6} "
                f"{'Input':<8} {'Output':<8} {'Total':<8} {'Context':<8}"
            )
            print("-" * 110)
            for session in sessions:
                s_id = session.session_id
                prov = session.provider or '?'
                mod = session.model or '?'
                ctx = str(session.context_peak) if session.context_peak else '-'
                print(
                    f"{s_id:<16} {prov:<10} {mod:<20} {session.model_turns:<6} "
                    f"{session.input_tokens:<8} {session.output_tokens:<8} "
                    f"{session.total_tokens:<8} {ctx:<8}"
                )

        return 0

    if args.governor_command == "flags":
        # Show feature flags
        try:
            flags = governor.resolve_features(home)
        except ValueError as e:
            print(f"Error resolving flags: {e}", file=sys.stderr)
            return 2

        if args.json:
            output = {}
            for key, value in flags.items():
                source = governor.feature_source(key, home)
                output[key] = {'value': value, 'source': source}
            print(json.dumps(output, indent=2))
        else:
            # Table output
            print(f"{'Feature':<30} {'Value':<6} {'Source':<10}")
            print("-" * 46)
            for key, value in sorted(flags.items()):
                source = governor.feature_source(key, home)
                print(f"{key:<30} {value!s:<6} {source:<10}")

        return 0

    if args.governor_command == "compare":
        # ROI analysis: compare on vs off arms
        all_sessions = governor.parse_telemetry(home)

        # Filter by glob patterns
        on_sessions = []
        off_sessions = []

        for session in all_sessions:
            if fnmatch.fnmatch(session.session_id, args.on):
                on_sessions.append(session)
            if fnmatch.fnmatch(session.session_id, args.off):
                off_sessions.append(session)

        # Classify ROI
        verdict = governor.classify_roi(on_sessions, off_sessions)

        if args.json:
            output = {
                'status': verdict.status,
                'reason': verdict.reason,
                'on_sessions': verdict.on_sessions,
                'off_sessions': verdict.off_sessions,
                'on_tokens': verdict.on_tokens,
                'off_tokens': verdict.off_tokens,
                'savings': verdict.savings,
                'neutral_band': verdict.neutral_band,
            }
            print(json.dumps(output, indent=2))
        else:
            # Text output
            print(f"ROI Verdict: {verdict.status}")
            print(f"  Reason: {verdict.reason}")
            print(f"  On arm: {verdict.on_sessions} sessions, {verdict.on_tokens} tokens")
            print(f"  Off arm: {verdict.off_sessions} sessions, {verdict.off_tokens} tokens")
            if verdict.savings is not None:
                print(f"  Savings: {verdict.savings} tokens")

    if args.governor_command == "profiles":
        profiles = governor.ABLATION_PROFILES
        if args.json:
            print(json.dumps(profiles, indent=2))
        else:
            print(f"{'Profile':<25} {'Active Features'}")
            print("-" * 75)
            for pname, pflags in profiles.items():
                active = [k for k, v in pflags.items() if v]
                active_str = ", ".join(active) if active else "(none / all OFF)"
                print(f"{pname:<25} {active_str}")
        return 0

    if args.governor_command == "profile":
        try:
            if args.env:
                env_vars = governor.get_profile_env(args.name)
                if args.json:
                    print(json.dumps(env_vars, indent=2))
                else:
                    for ek, ev in env_vars.items():
                        print(f"{ek}={ev}")
            else:
                profile = governor.get_ablation_profile(args.name)
                if args.json:
                    print(json.dumps(profile, indent=2))
                else:
                    print(f"Profile: {args.name}")
                    for k, v in profile.items():
                        print(f"  {k:<25} {v!s}")
            return 0
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2

    if args.governor_command == "check-budget":
        result = governor.check_budget(home, args.session, args.role)
        if args.json:
            print(json.dumps(result))
        else:
            print(f"state={result['state']} used={result['used']} cap={result['cap']}")
        # T3.1 §4: record the HARD/BLOCK determination once per invocation
        # (Prime calls this CLI subcommand at most once per turn -- never
        # per tool call -- so this satisfies "cache/dedupe per session+turn"
        # without extra state).
        if result["state"] == "HARD":
            import tomllib

            from . import decisions

            stage = "SHADOW"
            try:
                v2_path = home / "config" / "v2.toml"
                if v2_path.is_file():
                    v2_raw = tomllib.loads(v2_path.read_text(encoding="utf-8"))
                    candidate = (v2_raw.get("rollout") or {}).get("brainstem", "SHADOW")
                    if candidate in decisions._ROLLOUT_STAGES:
                        stage = candidate
            except Exception:
                pass
            try:
                decisions.record(
                    home,
                    kind="budget",
                    session_id=args.session,
                    task_id=None,
                    chosen={"decision": "BLOCK", "state": "HARD"},
                    alternatives=["ALLOW"],
                    propensity=1.0,
                    randomized=False,
                    policy_version="v3.1",
                    stage=stage,
                    inputs={"used": result["used"], "cap": result["cap"]},
                )
            except Exception:
                pass
        return 0

    return 2


def cmd_firewall(args) -> int:
    import json

    from . import firewall

    home = _home(args)

    if args.firewall_command == "reduce":
        if args.input_path:
            text = Path(args.input_path).read_text(encoding="utf-8", errors="replace")
        else:
            text = sys.stdin.read()

        res = firewall.reduce_observation(
            text,
            kind=args.kind,
            command=args.exec_command,
            tool=args.tool,
            session=args.session,
            home=home,
        )

        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        else:
            print(res.distilled_text)
        return 0

    if args.firewall_command == "expand":
        try:
            expanded = firewall.expand_observation(home, args.ref)
            sys.stdout.write(expanded)
            return 0
        except BrainError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2

    if args.firewall_command == "kinds":
        kinds = sorted(firewall.REDUCER_MAP.keys())
        if args.json:
            print(json.dumps(kinds, indent=2))
        else:
            print("Available Observation Firewall Reducers:")
            for k in kinds:
                print(f"  - {k}")
        return 0

    return 2


def cmd_vmem(args) -> int:
    import json

    from . import vmem

    home = _home(args)
    store = vmem.VMemStore(home, args.session_id)

    if args.vmem_command == "store":
        if args.content_path:
            content = Path(args.content_path).read_text(encoding="utf-8", errors="replace")
        else:
            content = sys.stdin.read()

        metadata = None
        if args.metadata:
            try:
                metadata = json.loads(args.metadata)
            except json.JSONDecodeError as exc:
                print(f"Error: --metadata must be valid JSON: {exc}", file=sys.stderr)
                return 2
            if not isinstance(metadata, dict):
                print("Error: --metadata must be a JSON object", file=sys.stderr)
                return 2

        obj = store.store_object(
            kind=args.kind,
            title=args.title,
            content=content,
            summary=args.summary,
            pinned=args.pinned,
            metadata=metadata,
        )
        if args.json:
            print(json.dumps(obj.to_dict(), indent=2))
        else:
            print(
                f"Stored {obj.kind.value} object: {obj.obj_id} "
                f"(title={obj.title!r}, state={obj.residency_state.value})"
            )
        return 0

    if args.vmem_command == "list":
        objs = store.list_objects(residency_state=args.state, kind=args.kind)
        if args.json:
            print(json.dumps([o.to_dict() for o in objs], indent=2))
        else:
            print(f"Context Virtual Memory objects ({len(objs)} items):")
            for o in objs:
                pinned_mark = " [PINNED]" if o.pinned else ""
                print(
                    f"  - {o.obj_id} [{o.residency_state.value}] {o.kind.value}: "
                    f"{o.title} (~{o.token_estimate}t){pinned_mark}"
                )
        return 0

    if args.vmem_command == "page":
        try:
            obj, content = store.fault_in(args.obj_id)
            if args.json:
                res = obj.to_dict()
                res["content"] = content
                print(json.dumps(res, indent=2))
            else:
                sys.stdout.write(content)
            return 0
        except BrainError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2

    if args.vmem_command == "resolve":
        # Part D: additive, does not reuse/alter the `page` branch above.
        # resolve_object() never raises (fails open with {"ok": False,
        # "error": ...}) — this branch only decides how to present that
        # result, it never needs its own BrainError handling.
        result = vmem.resolve_object(home, args.session_id, args.obj_id)
        if args.json:
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
        if not result.get("ok"):
            print(f"Error: {result.get('error', 'resolve failed')}", file=sys.stderr)
            return 2
        sys.stdout.write(str(result.get("content", "")))
        return 0

    if args.vmem_command == "claim-pages":
        # Defect B (RC4 proactive-paging-repair pass): reads a small
        # bounded JSON payload from stdin -- {"candidates": [{"obj_id":
        # ..., "kind": ...}, ...]} -- calls VMemStore.claim_pages, and
        # prints exactly the obj_ids actually claimed. Bounded, fast, no
        # LLM, no retrieval, no free text.
        try:
            raw_stdin = sys.stdin.read()
            payload = json.loads(raw_stdin) if raw_stdin.strip() else {}
        except json.JSONDecodeError as exc:
            print(f"Error: stdin must be valid JSON: {exc}", file=sys.stderr)
            return 2
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list):
            print(
                "Error: payload must be a JSON object with a 'candidates' array",
                file=sys.stderr,
            )
            return 2
        claimed = store.claim_pages(candidates)
        if args.json:
            print(json.dumps(claimed, indent=2))
        else:
            claimed_desc = ", ".join(claimed) if claimed else "(none)"
            print(f"Claimed {len(claimed)} of {len(candidates)} requested objects: {claimed_desc}")
        return 0

    if args.vmem_command == "hot-context":
        res = store.render_hot_context(max_tokens=args.budget)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(res["rendered_text"])
        return 0

    if args.vmem_command == "compact-prep":
        res = store.prepare_compaction()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(
                f"Compaction prepared: {res['evicted_at_compaction']} items evicted, "
                f"{res['pinned_preserved']} pinned preserved"
            )
        return 0

    if args.vmem_command == "compact-resume":
        res_text = store.resume_after_compaction(max_tokens=args.budget)
        print(res_text)
        return 0

    if args.vmem_command == "evict":
        victims = store.evict_to_budget(max_tokens=args.budget)
        if args.json:
            print(json.dumps([v.to_dict() for v in victims], indent=2))
        else:
            print(f"Evicted {len(victims)} objects to budget {args.budget}")
        return 0

    return 2


def cmd_action_cache(args) -> int:
    import json

    from . import action_cache

    home = _home(args)
    store = action_cache.ActionCacheStore(home)

    if args.action_cache_command == "stats":
        stats = store.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("Action Cache Statistics:")
            print(f"  Entries: {stats['total_entries']}")
            print(f"  Hits: {stats['total_hits']}")
            print(f"  Tokens Saved Estimate: {stats['tokens_saved_estimate']}")
            print("  Economics by dependency class:")
            for dependency_class, economics_row in stats[
                "economics_by_dependency_class"
            ].items():
                print(
                    f"    {dependency_class}: {economics_row['lookups']} lookups, "
                    f"{economics_row['hits']} hits, {economics_row['status']}"
                )
        return 0

    if args.action_cache_command == "get":
        res = store.query(args.action_key)
        if args.json:
            out = {
                "hit": res.hit,
                "reason": res.reason,
                "latency_ms": round(res.latency_ms, 3),
                "entry": res.entry.to_dict() if res.entry else None,
            }
            print(json.dumps(out, indent=2))
        else:
            if res.hit and res.content is not None:
                print(f"[CACHE HIT] {args.action_key} ({res.latency_ms:.3f}ms)")
                sys.stdout.write(res.content)
            else:
                print(f"[CACHE MISS] {args.action_key} ({res.reason})")
        return 0

    if args.action_cache_command == "invalidate":
        if args.invalidate_all:
            store.clear()
            print("Cleared all action cache entries.")
            return 0
        if args.path:
            count = store.invalidate_by_path(args.path)
            print(f"Invalidated {count} entries depending on {args.path}")
            return 0
        print("Specify --path <path> or --all to invalidate.", file=sys.stderr)
        return 2

    if args.action_cache_command == "clear":
        store.clear()
        print("Cleared action cache.")
        return 0

    if args.action_cache_command == "search":
        return _action_cache_search(home, args)

    return 2


def _code_search_git_tracked(target_dir: Path, pattern: str, max_matches: int) -> str:
    """
    Deterministic search over git-tracked files only (§ CODE_SEARCH, Phase
    R5). `git ls-files` output is deterministic for a fixed tree, so this is
    a pure function of (target_dir's git tree, pattern, max_matches) —
    exactly what the Action Cache's git_tree_hash proof gate requires.
    """
    import re
    import subprocess

    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        files = (
            [target_dir / p for p in res.stdout.splitlines() if p.strip()]
            if res.returncode == 0
            else []
        )
    except Exception:
        files = []

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"invalid pattern: {exc}"

    matches: list[str] = []
    for f in files:
        if len(matches) >= max_matches:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{f}:{lineno}:{line.strip()}")
                if len(matches) >= max_matches:
                    break

    if not matches:
        return f"0 matches for {pattern!r}"
    return "\n".join(matches)


def _action_cache_search(home: Path, args) -> int:
    """Search through a safe scoped WORKTREE proof, or compute directly."""
    import json
    import time

    from . import action_cache

    target_dir = (Path(args.path) if args.path else home).resolve()
    snapshot = action_cache.worktree_fingerprint_for(target_dir)
    compute = lambda: _code_search_git_tracked(
        target_dir,
        args.pattern,
        args.max_matches,
    )
    if snapshot is None:
        started = time.perf_counter()
        content = compute()
        latency_ms = (time.perf_counter() - started) * 1000.0
        was_hit = False
    else:
        proof = action_cache.ActionProof(
            dependency_class=action_cache.DependencyClass.WORKTREE,
            worktree_root=snapshot.repository_root,
            worktree_scope=snapshot.scope,
            worktree_fingerprint=snapshot.fingerprint,
            verification_predicate="git_tree_unchanged",
        )
        store = action_cache.ActionCacheStore(home)
        content, was_hit, latency_ms = store.get_or_execute(
            action_cache.ActionType.CODE_SEARCH,
            target=str(target_dir),
            params={
                "pattern": args.pattern,
                "max_matches": args.max_matches,
            },
            proof=proof,
            compute_fn=compute,
            output_summary=f"code search {args.pattern!r} under {target_dir}",
        )
    if args.json:
        print(
            json.dumps(
                {"hit": was_hit, "latency_ms": round(latency_ms, 3), "content": content},
                indent=2,
            )
        )
    else:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        print(
            f"[{'CACHE HIT' if was_hit else 'MISS (computed)'}, {latency_ms:.3f}ms]",
            file=sys.stderr,
        )
    return 0


def cmd_worker_plane(args) -> int:
    """
    Phase R7: the actual Brain-owned enforcement point for the worker
    concurrency ceiling. Prime's extension API (brainstem/prime-extension/
    types/prime.d.ts) exposes 11 lifecycle events and none of them is a
    spawn/subagent event — confirmed by exhaustive enumeration of the
    PrimeEvent union, see outputs/reports/rc4/02-prime-live-callgraph.md.
    WorkerPlaneManager.spawn_worker() already enforces the ceiling
    correctly (SQLite bookkeeping + a raised BrainError over the limit,
    tests/test_repository_intelligence_live.py::
    test_worker_concurrency_ceiling_enforcement); before this pass nothing
    outside its own module ever called it. This CLI subcommand makes it a
    real, invokable enforcement surface — the same "Brain-owned layer
    below the host" pattern as R5's action-cache search.
    """
    import json

    from . import worker_protocol
    from .repository_intelligence import (
        DEFAULT_MAX_WORKERS,
        WorkerPlaneManager,
        WorkerResultPacket,
        WorkerStatus,
    )

    home = _home(args)
    if args.worker_plane_command == "reap":
        error = None
        try:
            results = worker_protocol.reap(home)
        except Exception as exc:
            results = []
            error = f"{type(exc).__name__}: {exc}"
        output = {"reaped": results}
        if error:
            output["error"] = error
        if args.json:
            print(json.dumps(output, indent=2))
        elif error:
            print(f"worker-plane reap unavailable: {error}")
        else:
            for item in results:
                print(f"{item['task_id']}: {item['action']} ({item['state']})")
        return 0
    requested_max = getattr(args, "max_workers", None)
    max_workers = requested_max if requested_max is not None else DEFAULT_MAX_WORKERS
    plane = WorkerPlaneManager(home, args.session_id, max_concurrent_workers=max_workers)

    if args.worker_plane_command == "spawn":
        try:
            packet = plane.spawn_worker(
                args.subtask,
                target_files=args.target_files,
                relevant_symbols=args.relevant_symbols,
                context_capsule=args.context_capsule,
            )
        except BrainError as e:
            if args.json:
                print(json.dumps({"spawned": False, "error": str(e)}))
            else:
                print(f"Error: {e}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"spawned": True, **packet.to_dict()}, indent=2))
        else:
            print(f"Spawned {packet.worker_id} (session={args.session_id})")
        return 0

    if args.worker_plane_command == "complete":
        plane.complete_worker(
            WorkerResultPacket(
                worker_id=args.worker_id,
                session_id=args.session_id,
                status=WorkerStatus(args.status),
                summary=args.summary,
                findings=args.findings,
                tokens_used=args.tokens_used,
            )
        )
        if args.json:
            out = {"completed": True, "worker_id": args.worker_id, "status": args.status}
            print(json.dumps(out))
        else:
            print(f"Completed {args.worker_id}: {args.status}")
        return 0

    if args.worker_plane_command == "status":
        active = plane.active_worker_count()
        if args.json:
            print(
                json.dumps(
                    {"active_workers": active, "max_concurrent_workers": max_workers}, indent=2
                )
            )
        else:
            print(f"Active workers: {active}/{max_workers}")
        return 0

    return 2


def cmd_fresh_verifier(args) -> int:
    """
    Phase R9: the "record" half of fresh-verifier plumbing. Pairs with the
    existing `second_brain verify <session_id> <repo>`
    (verify.build_verifier_brief, Phase 7) for the "prepare" half — that
    already builds a real, deterministic, backward-reconstruction brief;
    this command only ever parses a verdict from a raw-response file the
    caller supplies, so it has no code path that can produce PASS/FAIL
    without that file actually existing.
    """
    import json

    from .fresh_verifier import VerifierProvenance, record_verifier_response

    if args.fresh_verifier_command != "record":
        return 2

    out_dir = Path(args.out)
    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists():
        print(f"Error: prompt file not found: {prompt_path}", file=sys.stderr)
        return 2
    raw_response_path = Path(args.raw_response)
    if not raw_response_path.exists():
        print(f"Error: raw response file not found: {raw_response_path}", file=sys.stderr)
        return 2

    prompt = prompt_path.read_text(encoding="utf-8")
    raw_response = raw_response_path.read_text(encoding="utf-8")
    provenance = VerifierProvenance(
        provider=args.provider,
        model=args.model,
        host=args.host,
        session_id=args.session_id,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
    )
    evidence = record_verifier_response(prompt, raw_response, provenance)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "provider": provenance.provider,
                "model": provenance.model,
                "host": provenance.host,
                "session_id": provenance.session_id_dict(),
                "prompt_file": str(prompt_path),
                "captured_at": evidence.captured_at,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "usage.json").write_text(
        json.dumps(provenance.usage_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "verdict.json").write_text(
        json.dumps(evidence.verdict.to_dict(), indent=2), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(evidence.to_dict(), indent=2))
    else:
        print(f"Verdict: {evidence.verdict.verdict}")
        if evidence.verdict.verdict == "UNPARSEABLE":
            print(
                "No 'Result: PASS|FAIL|PARTIAL' line found in the raw response — "
                "recorded as UNPARSEABLE, not guessed.",
                file=sys.stderr,
            )
        print(f"Evidence written to {out_dir}")
    return 0


def cmd_delta_sync(args) -> int:
    import json

    from . import delta_sync
    home = _home(args)

    if args.delta_sync_command == "diff":
        base_item = None
        if args.base_file != "null":
            base_item = json.loads(Path(args.base_file).read_text(encoding="utf-8"))
        target_item = json.loads(Path(args.target_file).read_text(encoding="utf-8"))

        delta = delta_sync.compute_memory_delta(base_item, target_item, home=home)
        if args.json:
            print(json.dumps(delta.to_dict(), indent=2))
        else:
            print(delta_sync.render_delta_sync_text([delta]))
        return 0

    if args.delta_sync_command == "apply":
        base_item = json.loads(Path(args.base_file).read_text(encoding="utf-8"))
        delta_dict = json.loads(Path(args.delta_file).read_text(encoding="utf-8"))
        delta = delta_sync.MemoryDeltaPacket.from_dict(delta_dict)

        try:
            updated = delta_sync.apply_delta(base_item, delta)
            print(json.dumps(updated, indent=2))
            return 0
        except BrainError as e:
            print(f"Error applying delta: {e}", file=sys.stderr)
            return 2

    if args.delta_sync_command == "sync":
        target_items = json.loads(Path(args.target_file).read_text(encoding="utf-8"))
        engine = delta_sync.DeltaSyncEngine(home=home, session_id=args.session_id)
        deltas, rendered = engine.sync_memories(
            args.session_id, target_items, recipient=args.recipient
        )
        if args.json:
            print(json.dumps([d.to_dict() for d in deltas], indent=2))
        else:
            print(rendered or "(all memories up to date)")
        return 0

    return 2


def cmd_cascade(args) -> int:
    import json

    from . import hybrid_retrieval

    home = _home(args)
    retriever = hybrid_retrieval.HybridCascadeRetriever()

    if args.cascade_command == "query":
        res = retriever.retrieve(
            home,
            args.query_text,
            project_id=args.project,
            confidence_threshold=args.threshold,
        )
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        else:
            print(
                f"Cascade Result: Tier {res.tier_resolved} | {res.decision} ({res.reason}) "
                f"[{res.latency_ms:.3f}ms]"
            )
            for m in res.matches:
                print(f"  - [{m.score:.2f}] {m.memory_id}: {m.title}")
        return 0

    if args.cascade_command == "clear-cache":
        retriever.invalidate_negative_cache(home)
        print("Cleared negative result cache.")
        return 0

    return 2



def cmd_backup(args) -> int:
    home = _home(args)
    bdir = backup_mod.create_backup(home, note=args.note)
    print(f"Backup created: {bdir}")
    return 0


def cmd_restore(args) -> int:
    home = _home(args)
    backup_mod.restore_backup(home, args.backup_dir, force=args.force)
    print(f"Restored from {args.backup_dir} into {home}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "project": cmd_project,
        "backup": cmd_backup,
        "heartbeat": cmd_heartbeat,
        "p4": cmd_p4,
        "restore": cmd_restore,
        "calibrate": cmd_calibrate,
        "telemetry": cmd_telemetry,
        "governor": cmd_governor,
        "firewall": cmd_firewall,
        "vmem": cmd_vmem,
        "action-cache": cmd_action_cache,
        "worker-plane": cmd_worker_plane,
        "fresh-verifier": cmd_fresh_verifier,
        "delta-sync": cmd_delta_sync,
        "cascade": cmd_cascade,
        "capsule": cmd_capsule,
        "scout": cmd_scout,
        "engrams": cmd_engrams,
        "models": cmd_models,
        "frontier": cmd_frontier,
        "immune": cmd_immune,
        "promote": cmd_promote,
        "demote": cmd_demote,
        "promotions": cmd_promotions,
        "credit": cmd_credit,
        "optimize": cmd_optimize,
        "router": cmd_router,
        "skills": cmd_skills,
        "reconsolidation": cmd_reconsolidation,
        "sleep": cmd_sleep,
        "working-set": cmd_working_set,
        "plasticity": cmd_plasticity,
        "cerebellum": cmd_cerebellum,
        "metacog": cmd_metacog,
        "remember": cmd_remember,
        "recall": cmd_recall,
        "memory": cmd_memory,
        "episodes": cmd_episodes,
        "env": cmd_env,
        "processes": cmd_processes,
        "radar": cmd_radar,
        "risk": cmd_risk,
        "v2": cmd_v2,
        "verify": cmd_verify,
        "artifact": cmd_artifact,
        "simplification": cmd_simplification,
        "requirements": cmd_requirements,
        "handoff": cmd_handoff,
        "read-ledger": cmd_read_ledger,
        "context": cmd_context,
        "autoinject": cmd_autoinject,
        "orchestration": cmd_orchestration,
        "ledger": cmd_ledger,
        "stop": cmd_stop,
        "session": cmd_session,
    }
    try:
        return handlers[args.command](args)
    except BrainError as exc:
        print(f"brainctl: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
