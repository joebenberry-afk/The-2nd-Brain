"""brainctl — Python control CLI (plan §82).

Implemented in Phase 1: init, doctor, status, project add|list|status,
backup, restore. Later phases add capture/recall/sleep/skills/... commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import (
    __version__,
    artifacts,
    db,
    envsteward,
    episodes,
    paths,
    registry,
    risk,
    scout,
    semantic,
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
        for a, b in pairs:
            print(f"{a['memory_id']} <-> {b['memory_id']}  (title {a['title']!r})")
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
