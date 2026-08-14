"""brainctl — Python control CLI (plan §82).

Implemented in Phase 1: init, doctor, status, project add|list|status,
backup, restore. Later phases add capture/recall/sleep/skills/... commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import cast

from . import (
    __version__,
    artifacts,
    cerebellum,
    credit,
    crossmodel,
    db,
    engram,
    envsteward,
    episodes,
    frontier,
    immune,
    monitor,
    paths,
    plasticity,
    promotion,
    reconsolidation,
    registry,
    risk,
    router,
    scout,
    semantic,
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
    sub.add_parser("doctor", parents=[home_parent], help="run health checks")
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

    rl = sub.add_parser("read-ledger", parents=[home_parent], help="Read Ledger (Phase 4)")
    rls = rl.add_subparsers(dest="read_ledger_command", required=True)
    rrec = rls.add_parser("record", parents=[home_parent], help="record a file read")
    rrec.add_argument("session_id")
    rrec.add_argument("path")
    rrec.add_argument("--purpose", default="")
    rrec.add_argument("--turn", type=int, default=None)
    rrec.add_argument("--range", dest="range_text", default=None)
    rrec.add_argument("--artifact", default=None)
    rlshow = rls.add_parser("show", parents=[home_parent], help="show the read ledger")
    rlshow.add_argument("session_id")

    cc = sub.add_parser("context", parents=[home_parent], help="JIT Context Compiler (Phase 4)")
    ccs = cc.add_subparsers(dest="context_command", required=True)
    ccomp = ccs.add_parser("compile", parents=[home_parent], help="compile a Task Context Capsule")
    ccomp.add_argument("session_id")
    ccomp.add_argument("task")
    ccomp.add_argument("--project", dest="project_key", default=None)

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

    vf = sub.add_parser("verify", parents=[home_parent], help="intent verifier brief (Phase 7)")
    vfs = vf.add_subparsers(dest="verify_command", required=True)
    vbuild = vfs.add_parser(
        "build-brief", parents=[home_parent], help="build a fresh-context verifier brief"
    )
    vbuild.add_argument("session_id")
    vbuild.add_argument("repo", type=Path)

    envp = sub.add_parser("env", parents=[home_parent], help="environment steward (Phase 8)")
    eps = envp.add_subparsers(dest="env_command", required=True)
    esnap = eps.add_parser(
        "snapshot", parents=[home_parent], help="capture an environment snapshot"
    )
    esnap.add_argument("repo", type=Path)
    esnap.add_argument("--session", dest="session_id", default=None)
    esnap.add_argument("--json", action="store_true", dest="as_json")

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

    mm = sub.add_parser("memory", parents=[home_parent], help="semantic memory (Phase 10)")
    mms = mm.add_subparsers(dest="memory_command", required=True)
    madd = mms.add_parser("add", parents=[home_parent], help="add a semantic memory (candidate)")
    madd.add_argument("title")
    madd.add_argument("body")
    madd.add_argument("--scope", default="project", choices=semantic.SCOPES)
    madd.add_argument("--project", dest="project_id", default="second-brain")
    madd.add_argument("--grade", default="OBSERVED", choices=semantic.GRADES)
    madd.add_argument("--source", dest="sources", action="append", default=None)
    mcur = mms.add_parser(
        "curate", parents=[home_parent], help="curate: set grade/status with rules"
    )
    mcur.add_argument("memory_id")
    mcur.add_argument("--grade", default=None, choices=semantic.GRADES)
    mcur.add_argument("--status", default=None, choices=semantic.STATUSES)
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
    result = doctor_mod.run_doctor(_home(args))
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
            text = sys.stdin.read()
            info = artifacts.store_text(home, text, args.kind, tool=args.tool, session=args.session)
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
    return 0


def cmd_verify(args) -> int:
    home = _home(args)
    path = verify.build_verifier_brief(home, args.session_id, args.repo)
    print(f"Verifier brief: {path}")
    return 0


def cmd_env(args) -> int:
    import json

    home = _home(args)
    snap = envsteward.snapshot(home, args.repo, session_id=args.session_id)
    if args.as_json:
        print(json.dumps(snap, indent=1, default=str))
    else:
        for k, v in snap.items():
            print(f"{k:18s} {v}")
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


def cmd_memory(args) -> int:
    home = _home(args)
    if args.memory_command == "add":
        mid = semantic.add_memory(
            home,
            args.title,
            args.body,
            scope=args.scope,
            project_id=args.project_id,
            grade=args.grade,
            sources=_parse_sources(args.sources),
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
        result = credit.counterfactual_eval(home, args.skill_name, tasks)
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
        fields: dict = {}
        for name, dest in (
            ("objective", "objective"),
            ("next_action", "next_action"),
            ("task_mode", "task_mode"),
            ("risk", "risk"),
            ("constraints", "constraints"),
            ("confirmed_facts", "confirmed_facts"),
            ("current_hypotheses", "current_hypotheses"),
            ("decisions_this_session", "decisions_this_session"),
            ("files_touched", "files_touched"),
            ("open_questions", "open_questions"),
            ("brain_refs", "brain_refs"),
            ("artifact_refs", "artifact_refs"),
        ):
            value = getattr(args, dest, None)
            if value is not None:
                fields[name] = value
        if not fields:
            print("brainctl: error: no update fields given", file=sys.stderr)
            return 2
        working_set.update_capsule(home, args.session_id, **fields)
        print("Capsule updated.")
        return 0
    if args.capsule_command == "show":
        print(json.dumps(working_set.show_capsule(home, args.session_id), indent=2))
        return 0
    return 2


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


def cmd_context(args) -> int:
    home = _home(args)
    if args.context_command == "compile":
        path = jit_mod.compile_context(
            home, args.session_id, args.task, project_key=args.project_key
        )
        print(f"Context capsule: {path}")
        return 0
    return 2


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
        "restore": cmd_restore,
        "telemetry": cmd_telemetry,
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
        "router": cmd_router,
        "skills": cmd_skills,
        "reconsolidation": cmd_reconsolidation,
        "sleep": cmd_sleep,
        "plasticity": cmd_plasticity,
        "cerebellum": cmd_cerebellum,
        "metacog": cmd_metacog,
        "memory": cmd_memory,
        "episodes": cmd_episodes,
        "env": cmd_env,
        "processes": cmd_processes,
        "risk": cmd_risk,
        "verify": cmd_verify,
        "artifact": cmd_artifact,
        "requirements": cmd_requirements,
        "read-ledger": cmd_read_ledger,
        "context": cmd_context,
    }
    try:
        return handlers[args.command](args)
    except BrainError as exc:
        print(f"brainctl: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
