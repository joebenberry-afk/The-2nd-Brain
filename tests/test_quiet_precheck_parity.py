"""Quiet fast path parity (V3 S2, QuietPath).

The in-host precheck may only answer `skip` when the Python pipeline would have
produced NO model-visible message for that prompt. This is the safety net for
that claim: both sides run over the SAME read-only snapshot of the LIVE corpus.

* Python side — `second_brain.turn_bridge.prepare_turn` with the
  capsule/render/autoinject phases (exactly what the shipped `turn prepare` batch
  runs), then the host's echo suppression applied to the rendered hot context
  (`activeStateMessage`, brainstem/prime-extension/src/active-state-mirror.ts). A
  message exists when the render survives that suppression or when the AutoInject
  decision carries a packet.
* TS side — `brainstem/prime-extension/tests/quiet-precheck-probe.ts`, executed by
  node (bun too, when present, to prove the extension's other supported host
  runtime agrees), importing the real `src/quiet-precheck.ts`.

Datasets: `outputs/reports/v3-s2/dev/cases.jsonl` (the exposed regressions and
tuning cases) and a deterministic fuzz set built from the snapshot corpus's own
title/summary tokens mixed with filler.

Asserted: zero violations of `skip => no Python message`, tokenizer and stopword
parity against the Python source of truth, and non-vacuity (the precheck does
skip, and Python does inject on some cases). Reported: skip rates per dataset
(the measured saving) and the precheck's in-host latency.
"""

from __future__ import annotations

import importlib.util
import json
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
from pathlib import Path
from typing import Any

import pytest

from second_brain import paths, semantic, turn_bridge, working_set
from second_brain.errors import BrainError

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_DIR = REPO_ROOT / "brainstem" / "prime-extension"
PROBE = EXTENSION_DIR / "tests" / "quiet-precheck-probe.ts"
DEV_CASES = REPO_ROOT / "outputs" / "reports" / "v3-s2" / "dev" / "cases.jsonl"
SNAPSHOT_HARNESS = REPO_ROOT / "scripts" / "v3_matched_arms.py"

HOT_CONTEXT_HEADER = "[SECOND_BRAIN_HOT_CONTEXT]"
CAPSULE_MAX_TEXT_CHARS = 512
PROBE_TIMEOUT_S = 600
FUZZ_SEED = 20260924
FUZZ_TOKEN_PROMPTS = 200
FUZZ_FILLER_PROMPTS = 100
WARM_FUZZ_EVERY = 10
WARMUP_PROMPT = "warmup placeholder token soup"

_FUZZ_TOKENS = re.compile(r"[a-z0-9]{3,}")
_FRAMES = (
    "{q}",
    "Explain {q} to me.",
    "Tell me about {q}.",
    "How should I handle {q}?",
    "Answer from your current context only: {q}",
    "Without reading any files, {q}",
    "Keep it to one line and {q}",
)
_FILLER = (
    "Summarize the paragraph above in two sentences.",
    "Format the answer as a markdown table with three columns and no bullet points.",
    "Rename the local variable tmp to buffer in this snippet: tmp = 1; print(tmp)",
    "Translate 'good morning' into French.",
    "Rewrite this sentence in the passive voice: the cat sat on the mat.",
    "What is 17 times 23?",
    "Reply with exactly: OK-42",
    "List three generic best practices for writing shell commands.",
)


def _snapshot_corpus() -> Any:
    """`scripts/v3_matched_arms.py::snapshot_corpus` (read-only live-corpus copy)."""
    spec = importlib.util.spec_from_file_location("v3_matched_arms_snapshot", SNAPSHOT_HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.snapshot_corpus


def _probe_runner() -> list[str]:
    """node is always available; bun proves the extension's other host runtime."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable: the quiet precheck probe cannot run")
    return [node]


def _run_probe(
    requests: list[dict[str, Any]], work: Path, runner: list[str]
) -> list[dict[str, Any]]:
    request_file = work / "requests.jsonl"
    if not request_file.exists():
        request_file.write_text(
            "".join(json.dumps(request) + "\n" for request in requests), encoding="utf-8"
        )
    completed = subprocess.run(
        [*runner, str(PROBE), "--requests", str(request_file)],
        cwd=str(EXTENSION_DIR),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
    )
    assert completed.returncode == 0, f"probe failed: {completed.stderr[-2000:]}"
    results = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert len(results) == len(requests), "probe must answer one result per request"
    return results


def _run_probe_stopwords() -> list[str]:
    completed = subprocess.run(
        [*_probe_runner(), str(PROBE), "--stopwords"],
        cwd=str(EXTENSION_DIR),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
    )
    assert completed.returncode == 0, f"probe failed: {completed.stderr[-2000:]}"
    return list(json.loads(completed.stdout)["stopwords"])


def _render_message(prompt: str, capsule_ok: bool, rendered_text: str | None) -> bool:
    """`activeStateMessage` (host): a non-echo render is a model-visible message."""
    if not capsule_ok or not rendered_text:
        return False
    text = rendered_text
    echo = f"{HOT_CONTEXT_HEADER}\nObjective: {prompt.strip()[:CAPSULE_MAX_TEXT_CHARS].strip()}"
    if text == echo or text.startswith(f"{echo}\n"):
        text = HOT_CONTEXT_HEADER + text[len(echo) :]
    return text.strip() != HOT_CONTEXT_HEADER


def _python_decision(snapshot: Path, session: str, prompt: str, cwd: Path) -> dict[str, Any]:
    """What the shipped Python pipeline would have produced for this prompt."""
    out = turn_bridge.prepare_turn(
        snapshot,
        session_id=session,
        task=prompt,
        objective=prompt,
        next_action=prompt,
        cwd=str(cwd),
        want=("capsule", "render", "autoinject"),
    )
    rendered_text: str | None = None
    if out.get("render_stdout"):
        rendered_text = json.loads(out["render_stdout"]).get("rendered_text")
    packet: str | None = None
    if out.get("autoinject_stdout"):
        packet = json.loads(out["autoinject_stdout"]).get("packet")
    capsule_ok = bool(out.get("capsule")) and not out.get("capsule_error")
    return {
        "message": _render_message(prompt, capsule_ok, rendered_text) or bool(packet),
        "packet": bool(packet),
        "rendered_chars": len(rendered_text or ""),
    }


def _python_query_text(prompt: str) -> str | None:
    """`quietQueryText`: the retrieval text the precheck is allowed to use."""
    stripped = prompt.strip()
    if not stripped:
        return None
    bounded = stripped[:CAPSULE_MAX_TEXT_CHARS]
    if bounded != bounded.rstrip() or any(ord(char) > 127 for char in bounded):
        return None
    return bounded


def _corpus_tokens(snapshot: Path) -> list[list[str]]:
    """Per-memory lowercased title+summary tokens, stopwords dropped."""
    db_file = (snapshot / "db" / "brain.sqlite").as_posix()
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT title, summary FROM memories ORDER BY memory_id").fetchall()
    finally:
        conn.close()
    stopwords = semantic._QUERY_STOPWORD_TOKENS
    tokens: list[list[str]] = []
    for title, summary in rows:
        found = [
            token
            for token in _FUZZ_TOKENS.findall(f"{title or ''} {summary or ''}".lower())
            if token not in stopwords
        ]
        if found:
            tokens.append(sorted(set(found)))
    return tokens


def _fuzz_prompts(snapshot: Path) -> list[tuple[str, str]]:
    """Deterministic fuzz: corpus-vocabulary prompts mixed with filler prompts."""
    rng = random.Random(FUZZ_SEED)
    memories = _corpus_tokens(snapshot)
    assert memories, "the snapshot corpus has no tokenizable memories"
    prompts: list[tuple[str, str]] = []
    for _ in range(FUZZ_TOKEN_PROMPTS):
        chosen = rng.choice(memories)
        count = min(len(chosen), rng.randint(1, 6))
        question = " ".join(rng.sample(chosen, count))
        prompts.append(("token", rng.choice(_FRAMES).format(q=question)))
    for _ in range(FUZZ_FILLER_PROMPTS):
        prompts.append(("filler", rng.choice(_FILLER)))
    # Long prompts exercise the 512-char retrieval-text boundary and its echo rule.
    prompts.append(("long_boundary", "runtime-state-ledger-" * 30))
    prompts.append(("long_boundary", f"{'runtime state ledger ' * 24}tail"))
    return prompts


def _dev_prompts() -> list[tuple[str, str, bool]]:
    """(id, prompt, expects_a_memory) for the exposed dev cases."""
    cases = [
        json.loads(line)
        for line in DEV_CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [(case["id"], case["prompt"], bool(case["expect"])) for case in cases]


def _median_p95(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"median": 0.0, "p95": 0.0}
    rank = min(len(ordered) - 1, max(0, int(0.95 * len(ordered)) - 1))
    return {"median": round(statistics.median(ordered), 3), "p95": round(ordered[rank], 3)}


def _measure(work: Path) -> dict[str, Any]:
    live_home = paths.resolve_home()
    live_db = live_home / "db" / "brain.sqlite"
    if not live_db.is_file():
        pytest.skip(f"live corpus not found at {live_db}")
    snapshot = work / "snapshot"
    _snapshot_corpus()(live_home, snapshot)

    entries: list[dict[str, Any]] = []
    for case_id, prompt, expects_memory in _dev_prompts():
        entries.append(
            {
                "dataset": "dev",
                "name": case_id,
                "prompt": prompt,
                "expects_memory": expects_memory,
                "warm": True,
            }
        )
    for index, (kind, prompt) in enumerate(_fuzz_prompts(snapshot)):
        entries.append(
            {
                "dataset": "fuzz",
                "name": f"fuzz-{index:03d}-{kind}",
                "prompt": prompt,
                "expects_memory": False,
                "warm": index % WARM_FUZZ_EVERY == 0,
            }
        )

    # ---- TS side: one probe process, one decision per entry ------------------
    requests = [
        {
            "index": index,
            "home": str(snapshot),
            "session": f"quiet-{entry['name'].lower()}",
            "prompt": entry["prompt"],
        }
        for index, entry in enumerate(entries)
    ]
    ts_results = _run_probe(requests, work, _probe_runner())

    # ---- Python side: the real pipeline per entry (fresh session) ------------
    for entry in entries:
        session = f"quiet-{entry['name'].lower()}"
        if entry["warm"]:
            # A stale capsule objective: the real turn-N+1 shape.
            _python_decision(snapshot, session, WARMUP_PROMPT, live_home)
        entry["session"] = session
        entry["python"] = _python_decision(snapshot, session, entry["prompt"], live_home)

    stopwords = _run_probe_stopwords()
    results = []
    for entry, ts in zip(entries, ts_results, strict=True):
        results.append({**entry, "ts": ts})
    return {
        "results": results,
        "stopwords": stopwords,
        "snapshot": snapshot,
        "work": work,
        "requests": requests,
    }


# ---------------------------------------------------------------------------
# Review counterexamples (V3 S2 review). Each case is asserted BOTH ways: the
# precheck must answer `run` AND the Python side must be non-vacuous — a message
# the precheck used to lose, or a capsule shape Python's loader really rejects.
# ---------------------------------------------------------------------------
NON_ASCII_MEMORY_ID = "mem-quiet-review-strasse"
NON_ASCII_MEMORY_TITLE = "Straße rollout"
NON_ASCII_MEMORY_BODY = "strasse sign"
CAPSULE_PROBE_PROMPT = "crosscheck parity probe"
CAPSULE_MAX_TEXT_CHARS = 512


def _canonical_capsule() -> dict[str, Any]:
    """`working_set.CAPSULE_FIELDS` as `_validate_capsule_fields` accepts them."""
    return {
        "objective": "quiet parity capsule",
        "task_mode": "STANDARD",
        "risk": "MEDIUM",
        "constraints": [],
        "confirmed_facts": [],
        "current_hypotheses": [],
        "decisions_this_session": [],
        "files_touched": [],
        "open_questions": [],
        "verification": {},
        "next_action": "",
        "brain_refs": [],
        "artifact_refs": [],
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _capsule_shapes() -> list[tuple[str, Any]]:
    """Capsule files Python's `_load_capsule` REJECTS (its own loader is the oracle)."""
    return [
        ("not_an_object", []),
        ("missing_fields", {"objective": "x", "decisions_this_session": [], "open_questions": []}),
        ("bad_task_mode", {**_canonical_capsule(), "task_mode": "PLAN"}),
        ("bad_risk", {**_canonical_capsule(), "risk": "low"}),
        ("empty_objective", {**_canonical_capsule(), "objective": "   "}),
        ("bad_list_field", {**_canonical_capsule(), "constraints": "not a list"}),
        ("bad_list_item", {**_canonical_capsule(), "open_questions": [1]}),
        ("bad_verification", {**_canonical_capsule(), "verification": {"ok": ["nested"]}}),
        ("bad_next_action", {**_canonical_capsule(), "next_action": None}),
        ("empty_updated_at", {**_canonical_capsule(), "updated_at": ""}),
    ]


def _insert_memory(snapshot: Path, *, memory_id: str, title: str, summary: str, body: str) -> None:
    """One canonical memory: markdown file + memories/memory_index/memory_fts rows.

    `scope='global'` keeps it retrievable under any project filter, and the index
    hash is the file's own sha256 so `semantic._search_fts` keeps the row fresh.
    """
    import hashlib

    relative = f"memory/semantic/{memory_id}__v1.md"
    body_file = snapshot / relative
    body_file.parent.mkdir(parents=True, exist_ok=True)
    body_file.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body_file.read_bytes()).hexdigest()
    stamp = "2026-01-01T00:00:00+00:00"
    conn = sqlite3.connect(snapshot / "db" / "brain.sqlite")
    try:
        conn.execute(
            "INSERT INTO memories (memory_id, title, scope, project_id, status, evidence_grade, "
            "current_version, created_at, updated_at, summary, body_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory_id,
                title,
                "global",
                None,
                "current",
                "TESTED",
                1,
                stamp,
                stamp,
                summary,
                relative,
            ),
        )
        conn.execute(
            "INSERT INTO memory_index (memory_id, title, summary, project_id, scope, status, "
            "evidence_grade, current_version, created_at, updated_at, body_path, tags, file_hash, "
            "indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory_id,
                title,
                summary,
                None,
                "global",
                "current",
                "TESTED",
                1,
                stamp,
                stamp,
                relative,
                "",
                digest,
                stamp,
            ),
        )
        conn.execute(
            "INSERT INTO memory_fts (memory_id, title, summary, body, project_id, status, "
            "evidence_grade, tags) VALUES (?,?,?,?,?,?,?,?)",
            (memory_id, title, summary, body, None, "current", "TESTED", ""),
        )
        conn.commit()
    finally:
        conn.close()


def _body_only_term(snapshot: Path) -> str:
    """One token that lives in BODIES only, and never in a headline.

    A plan built from such a term retrieves rows but can never contribute: rule 1
    needs a headline confirmation, rule 2 needs two near-unique terms, and a term
    this widespread cannot prove ubiquity for rule 3 either. That is exactly the
    plan shape the precheck legitimately skips on, so the counterexample below
    needs it to be real — verified against the corpus rather than assumed.
    """
    conn = sqlite3.connect(snapshot / "db" / "brain.sqlite")
    try:
        rows = conn.execute(
            "SELECT f.body AS body, "
            "COALESCE(m.title, '') || ' ' || COALESCE(m.summary, '') AS headline "
            "FROM memory_fts f JOIN memories m ON m.memory_id = f.memory_id"
        ).fetchall()
        total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        spread = {
            term: int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", (f'"{term}"*',)
                ).fetchone()[0]
            )
            for term in sorted(
                {
                    token
                    for body, _headline in rows
                    for token in _FUZZ_TOKENS.findall(str(body or "").casefold())
                }
            )
        }
    finally:
        conn.close()
    headline_tokens = {
        token
        for _body, headline in rows
        for token in _FUZZ_TOKENS.findall(str(headline or "").casefold())
    }
    candidates = [
        term
        for term in spread
        if spread[term] >= 1
        and spread[term] <= 0.5 * total
        and term not in semantic._QUERY_STOPWORD_TOKENS
        and not any(token.startswith(term) for token in headline_tokens)
    ]
    assert candidates, "the snapshot corpus has no body-only term to bound a plan with"
    return candidates[0]


def _write_capsule(snapshot: Path, session: str, capsule: Any) -> None:
    directory = snapshot / "state" / "sessions" / session
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "active-state.json").write_text(json.dumps(capsule), encoding="utf-8")


def _review_measure(work: Path) -> dict[str, Any]:
    live_home = paths.resolve_home()
    live_db = live_home / "db" / "brain.sqlite"
    if not live_db.is_file():
        pytest.skip(f"live corpus not found at {live_db}")
    snapshot = work / "snapshot"
    _snapshot_corpus()(live_home, snapshot)
    _insert_memory(
        snapshot,
        memory_id=NON_ASCII_MEMORY_ID,
        title=NON_ASCII_MEMORY_TITLE,
        summary="s",
        body=NON_ASCII_MEMORY_BODY,
    )

    entries: list[dict[str, Any]] = [
        {
            "name": "non_ascii_row",
            "session": "quiet-review-non-ascii",
            "prompt": "strasse",
            "expect_reason": "non_ascii_row",
        }
    ]
    for name, capsule in _capsule_shapes():
        entries.append(
            {
                "name": f"capsule_{name}",
                "session": f"quiet-review-capsule-{name}",
                "prompt": CAPSULE_PROBE_PROMPT,
                "expect_reason": "capsule_unreadable",
                "capsule": capsule,
            }
        )
    # The reviewer's shared shape: a long prompt whose first 512 characters carry
    # a plan the precheck can only skip on (a body-only ubiquitous term, verified
    # against this corpus), a capsule Python's loader rejects (so
    # `autoinject._retrieval_query_text` falls back to the FULL task text), and the
    # contributing term after that boundary.
    term = _body_only_term(snapshot)
    repeats = CAPSULE_MAX_TEXT_CHARS // (len(term) + 1) + 10
    filler = f"{term}-" * repeats
    fallback_prompt = f"{filler} strasse"
    assert len(fallback_prompt) > CAPSULE_MAX_TEXT_CHARS
    assert len(filler) > CAPSULE_MAX_TEXT_CHARS
    assert not filler[:CAPSULE_MAX_TEXT_CHARS].endswith(" ")
    entries.append(
        {
            "name": "capsule_fallback",
            "session": "quiet-review-capsule-fallback",
            "prompt": fallback_prompt,
            "expect_reason": "capsule_unreadable",
            "capsule": {"objective": "x", "decisions_this_session": [], "open_questions": []},
        }
    )
    # The control: the SAME bounded text on its own, with a canonical capsule. The
    # precheck's own answer for the only text it may use must be `skip` — that is
    # what makes the long prompt above a real counterexample rather than a case
    # that would have run anyway.
    entries.append(
        {
            "name": "bounded_plan_control",
            "session": "quiet-review-bounded-control",
            "prompt": filler,
            "expect_reason": "no_evidence",
            "capsule": _canonical_capsule(),
            "expect_decision": "skip",
        }
    )

    for entry in entries:
        if "capsule" in entry:
            _write_capsule(snapshot, entry["session"], entry["capsule"])
    requests = [
        {
            "index": index,
            "home": str(snapshot),
            "session": entry["session"],
            "prompt": entry["prompt"],
        }
        for index, entry in enumerate(entries)
    ]
    ts_results = _run_probe(requests, work, _probe_runner())

    results: list[dict[str, Any]] = []
    for entry, ts in zip(entries, ts_results, strict=True):
        record: dict[str, Any] = {**entry, "ts": ts}
        # Python's own loader is the oracle for the capsule shape: a rejected
        # capsule means `ensure_capsule` fails and AutoInject reads the full task.
        loader_rejects = False
        if "capsule" in entry:
            try:
                working_set.show_capsule(snapshot, entry["session"])
            except BrainError:
                loader_rejects = True
        record["loader_rejects"] = loader_rejects
        if entry["name"] in {"non_ascii_row", "capsule_fallback"}:
            record["python"] = _python_decision(
                snapshot, entry["session"], entry["prompt"], live_home
            )
        results.append(record)
    return {"results": results, "snapshot": snapshot, "work": work}


@pytest.fixture(scope="module")
def quiet_review(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    measured = _review_measure(tmp_path_factory.mktemp("quiet-review"))
    report = {
        "cases": len(measured["results"]),
        "skip_decisions": sum(1 for row in measured["results"] if row["ts"]["decision"] == "skip"),
        "skip_names": [
            row["name"] for row in measured["results"] if row["ts"]["decision"] == "skip"
        ],
        "reasons": sorted({row["ts"]["reason"] for row in measured["results"]}),
        "skip_rate": _rate(measured["results"], lambda row: row["ts"]["decision"] == "skip"),
    }
    print("\nquiet review counterexample report:\n" + json.dumps(report, indent=2, sort_keys=True))
    measured["report"] = report
    return measured


@pytest.fixture(scope="module")
def quiet_parity(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    work = tmp_path_factory.mktemp("quiet-parity")
    measured = _measure(work)
    results = measured["results"]
    report = _report(results)
    print("\nquiet precheck parity report:\n" + json.dumps(report, indent=2, sort_keys=True))
    measured["report"] = report
    return measured


def _rate(rows: list[dict[str, Any]], predicate: Any) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 4)


def _report(results: list[dict[str, Any]]) -> dict[str, Any]:
    dev = [row for row in results if row["dataset"] == "dev"]
    fuzz = [row for row in results if row["dataset"] == "fuzz"]
    no_benefit = [row for row in dev if not row["expects_memory"]]
    memory = [row for row in dev if row["expects_memory"]]
    skips = [row for row in results if row["ts"]["decision"] == "skip"]
    violations = [row for row in skips if row["python"]["message"]]
    latencies = [row["ts"]["ms"] for row in results]
    return {
        "prompts": len(results),
        "skip_rate_all": _rate(results, lambda row: row["ts"]["decision"] == "skip"),
        "skip_rate_dev_no_benefit": _rate(no_benefit, lambda row: row["ts"]["decision"] == "skip"),
        "skip_rate_dev_memory": _rate(memory, lambda row: row["ts"]["decision"] == "skip"),
        "skip_rate_fuzz": _rate(fuzz, lambda row: row["ts"]["decision"] == "skip"),
        "skip_rate_fuzz_token": _rate(
            [row for row in fuzz if row["name"].endswith("token")],
            lambda row: row["ts"]["decision"] == "skip",
        ),
        "skip_rate_fuzz_filler": _rate(
            [row for row in fuzz if row["name"].endswith("filler")],
            lambda row: row["ts"]["decision"] == "skip",
        ),
        "python_message_rate": _rate(results, lambda row: row["python"]["message"]),
        "python_packet_rate": _rate(results, lambda row: row["python"]["packet"]),
        "violations": len(violations),
        "violation_names": [row["name"] for row in violations],
        "skip_reasons": {
            reason: sum(1 for row in skips if row["ts"]["reason"] == reason)
            for reason in sorted({row["ts"]["reason"] for row in skips})
        },
        "precheck_ms": {**_median_p95(latencies), "max": round(max(latencies), 3)},
        "precheck_ms_dev_no_benefit": _median_p95([row["ts"]["ms"] for row in no_benefit]),
        "run_reasons": {
            reason: sum(1 for row in results if row["ts"]["reason"] == reason)
            for reason in sorted(
                {row["ts"]["reason"] for row in results if row["ts"]["decision"] == "run"}
            )
        },
    }


def test_stopword_set_matches_python(quiet_parity: dict[str, Any]) -> None:
    """Tokenizer drift is asymmetric: a token TS keeps only widens the check, a
    token TS drops could hide a contributing term."""
    assert quiet_parity["stopwords"] == sorted(semantic._QUERY_STOPWORD_TOKENS)


def test_tokenization_matches_python(quiet_parity: dict[str, Any]) -> None:
    """The TS candidate tokens must equal Python's for the retrieval text."""
    checked = 0
    for row in quiet_parity["results"]:
        query_text = _python_query_text(row["prompt"])
        if query_text is None:
            continue  # the precheck declined the prompt shape and answers run
        checked += 1
        assert row["ts"]["candidates"] == list(semantic._query_candidates(query_text)), (
            f"token drift on {row['name']}"
        )
    assert checked >= len(quiet_parity["results"]) - 5


def test_same_decisions_under_bun(quiet_parity: dict[str, Any]) -> None:
    """The extension runs under node or bun; both must decide identically."""
    bun = shutil.which("bun")
    if bun is None:
        pytest.skip("bun is not installed")
    results = _run_probe(quiet_parity["requests"], quiet_parity["work"], [bun])
    for row, bun_result in zip(quiet_parity["results"], results, strict=True):
        assert bun_result["decision"] == row["ts"]["decision"], row["name"]
        assert bun_result["reason"] == row["ts"]["reason"], row["name"]
        assert bun_result["candidates"] == row["ts"]["candidates"], row["name"]


def test_no_skip_where_python_produces_a_message(quiet_parity: dict[str, Any]) -> None:
    """The one invariant: `skip` never loses memory the Python pipeline delivers."""
    violations = [
        row
        for row in quiet_parity["results"]
        if row["ts"]["decision"] == "skip" and row["python"]["message"]
    ]
    assert violations == [], [
        {"name": row["name"], "reason": row["ts"]["reason"], "python": row["python"]}
        for row in violations
    ]


def test_parity_evidence_is_not_vacuous(quiet_parity: dict[str, Any]) -> None:
    """Skipping nothing, or injecting nothing, would make the parity check empty."""
    report = quiet_parity["report"]
    assert report["violations"] == 0
    assert report["skip_rate_all"] > 0
    assert report["python_message_rate"] > 0
    # Recall sanity: every dev case that needs a memory keeps the Python path.
    assert report["skip_rate_dev_memory"] == 0
    assert report["skip_rate_dev_no_benefit"] > 0
    assert report["precheck_ms"]["p95"] <= 50.0


def test_every_skip_carries_the_measured_saving(quiet_parity: dict[str, Any]) -> None:
    """A skip turn is exactly the turn whose Python phases never ran here."""
    for row in quiet_parity["results"]:
        if row["ts"]["decision"] != "skip":
            continue
        assert row["python"]["message"] is False
        assert row["ts"]["detail"]["total_documents"] > 0
        assert row["ts"]["candidates"], f"{row['name']} skipped without any candidate term"


def test_review_non_ascii_row_is_not_skipped(quiet_review: dict[str, Any]) -> None:
    """Review counterexample: Python folds row text with `str.casefold()`, where
    `"Straße"` becomes `"strasse"`, so a memory whose HEADLINE carries the ASCII
    query only through case folding still contributes (rule 1). Matching it with
    `toLowerCase()` misses that confirmation, so the precheck must answer `run`
    for any retrieved row whose text is not ASCII."""
    row = next(item for item in quiet_review["results"] if item["name"] == "non_ascii_row")
    assert row["ts"]["decision"] == "run", row
    assert row["ts"]["reason"] == row["expect_reason"], row
    # Non-vacuous: Python really does deliver a message for this prompt.
    assert row["python"]["message"] is True, row
    assert row["python"]["packet"] is True, row


def test_review_invalid_capsules_answer_run(quiet_review: dict[str, Any]) -> None:
    """Review counterexample: two empty arrays are not a canonical capsule →
    `ensure_capsule` fails and AutoInject falls back to the FULL task text, so an
    assumed 512-char bounded query can lose the contributing term. Every shape
    Python's loader rejects must answer `run` with a reason this module reports."""
    cases = [row for row in quiet_review["results"] if row["name"].startswith("capsule_")]
    assert len(cases) >= len(_capsule_shapes())
    for row in cases:
        assert row["loader_rejects"] is True, row
        assert row["ts"]["decision"] == "run", row
        assert row["ts"]["reason"] == row["expect_reason"], row


def test_review_capsule_fallback_keeps_the_message(quiet_review: dict[str, Any]) -> None:
    """The shared shape behind the capsule counterexample: a prompt longer than
    the 512-char objective boundary whose contributing term sits past it. With a
    capsule Python rejects, the pipeline retrieves with the whole task text and
    still delivers a message — so `skip` here would have lost it."""
    row = next(item for item in quiet_review["results"] if item["name"] == "capsule_fallback")
    assert len(row["prompt"]) > CAPSULE_MAX_TEXT_CHARS
    assert row["ts"]["decision"] == "run", row
    assert row["ts"]["reason"] == "capsule_unreadable", row
    assert row["python"]["message"] is True, row
    # The evidence lives past the boundary the precheck would otherwise assume.
    assert "strasse" not in row["prompt"][:CAPSULE_MAX_TEXT_CHARS]

    # The control proves the counterexample: the bounded text alone keeps its
    # skip, so the message above comes from the text Python adds back.
    control = next(
        item for item in quiet_review["results"] if item["name"] == "bounded_plan_control"
    )
    assert control["loader_rejects"] is False, control
    assert control["ts"]["decision"] == "skip", control
    assert control["ts"]["reason"] == "no_evidence", control


def test_review_counterexamples_report(quiet_review: dict[str, Any]) -> None:
    """The counterexample fixture is measured, not merely asserted: the ONLY skip
    it contains is the bounded-text control that proves the counterexample."""
    report = quiet_review["report"]
    assert report["cases"] >= len(_capsule_shapes()) + 3
    assert report["skip_decisions"] == 1, report
    assert report["skip_names"] == ["bounded_plan_control"], report
