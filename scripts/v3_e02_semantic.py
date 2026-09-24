#!/usr/bin/env python
"""V3 S2 E02 — corrected lexical vs small local dense encoder vs hybrid (RRF).

Bounded experiment on the **dev** split only (`outputs/reports/v3-s2/dev/cases.jsonl`).
The frozen held-out set is never opened, referenced or measured here by construction:
`_load_cases` refuses any path containing a `heldout` component.

Arms (all over one read-only snapshot of the live corpus):

  lexical       the production pipeline. Retrieval is a mirror of
                `autoinject.prepare_injection`'s `retrieve_rows` (cascade over the
                project filter + unscoped supplement + the full-then-focused query
                retry); the decision is the real `autoinject.prepare_injection`
                (cascade -> contribution filter -> validity/freshness/role/budget).
  dense:<enc>   small local CPU encoder, exact cosine over every admissible memory,
                then the same admission tail (the ROI token-cost stage is reported,
                not applied: it is calibrated to the lexical score scale).
  hybrid:<enc>  Reciprocal Rank Fusion (k=60) of the lexical and dense rankings.

Measured per arm: required-memory recall@k, no-benefit false-candidate rate at the
decision threshold (plus a full floor sweep, with and without the production score-gap
rule), injected packet tokens, cold load time, warm query latency, index build time,
resident + peak working set (Win32 GetProcessMemoryInfo) and offline operation (every
model file resolved locally; children run with HF_HUB_OFFLINE=1, a dead HTTP(S) proxy
and, for encoder arms, every socket connect blocked in-process).

Commands:
  python scripts/v3_e02_semantic.py prefetch [--model-dir DIR]
  python scripts/v3_e02_semantic.py run [--out DIR] [--model-dir DIR] [--reps N]
  python scripts/v3_e02_semantic.py summarize [results.json]
  python scripts/v3_e02_semantic.py child --arm ARM --encoder ENC --corpus DIR --out F
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
CANONICAL = WORKTREE.parents[1] if WORKTREE.parent.name == ".worktrees" else WORKTREE
PROCESS_START = time.perf_counter()
DEV_CASES = WORKTREE / "outputs" / "reports" / "v3-s2" / "dev" / "cases.jsonl"
OUT_DIR = WORKTREE / "outputs" / "reports" / "v3-s2" / "e02"
DEFAULT_MODEL_DIR = Path(tempfile.gettempdir()) / "v3_e02_models"
VALIDATION_RULE = (
    "dense/hybrid must beat corrected lexical recall by >=5 points "
    "at equal-or-better abstention"
)

MAX_CANDIDATES = 10  # autoinject._MAX_CANDIDATES: the product's candidate ceiling
RRF_K = 60
RAM_BUDGET_MIB = 1024.0

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "m2v-potion-8m": {"kind": "model2vec", "repo": "minishlab/potion-base-8M"},
    "onnx-minilm-l6": {
        "kind": "onnx",
        "repo": "Xenova/all-MiniLM-L6-v2",
        "files": ("tokenizer.json", "onnx/model_quantized.onnx"),
    },
}
ENCODERS = tuple(MODEL_SPECS)
ARMS = (
    "lexical",
    *(f"dense:{e}" for e in ENCODERS),
    *(f"hybrid:{e}" for e in ENCODERS),
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path, *, normalize_newlines: bool = False) -> str:
    data = path.read_bytes()
    if normalize_newlines:
        data = data.replace(b"\r\n", b"\n")
    return _sha256_bytes(data)


def _load_matched_arms() -> Any:
    """Reuse the S1 harness's read-only corpus snapshot (single implementation)."""
    spec = importlib.util.spec_from_file_location(
        "v3_matched_arms", WORKTREE / "scripts" / "v3_matched_arms.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cases(path: Path) -> list[dict[str, Any]]:
    parts = [p.lower() for p in path.parts]
    if "heldout" in parts or "held-out" in parts:
        raise SystemExit(f"refusing to open a held-out case file: {path}")
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for case in cases:
        if not {"id", "category", "prompt", "expect"} <= set(case):
            raise SystemExit(f"malformed case: {case.get('id')}")
    return cases


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _memory_fn() -> Any:
    """K32/psapi GetProcessMemoryInfo with explicit x64 argtypes (handle truncation)."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    function = getattr(ctypes.WinDLL("psapi", use_last_error=True), "GetProcessMemoryInfo", None)
    if function is None:
        function = kernel32.K32GetProcessMemoryInfo
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    function.restype = ctypes.c_int
    return function, kernel32.GetCurrentProcess()


def process_memory() -> dict[str, float]:
    """Working set (resident) and peak working set of THIS process (Win32)."""
    handle = _memory_fn()
    if handle is None:
        return {}
    function, process = handle
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not function(process, ctypes.byref(counters), counters.cb):
        return {}
    mib = 1024.0 * 1024.0
    return {
        "resident_mib": round(counters.WorkingSetSize / mib, 2),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / mib, 2),
        "pagefile_mib": round(counters.PagefileUsage / mib, 2),
        "peak_pagefile_mib": round(counters.PeakPagefileUsage / mib, 2),
    }


def network_probe(timeout: float = 3.0) -> dict[str, Any]:
    """Empirical offline check: with the child's dead proxy + offline flags, an HTTP
    client in the child environment cannot reach the internet."""
    import socket
    import urllib.request

    result: dict[str, Any] = {"target": "https://huggingface.co", "timeout_s": timeout}
    try:
        socket.setdefaulttimeout(timeout)
        response = urllib.request.urlopen("https://huggingface.co", timeout=timeout)
        result["reachable"] = True
        result["status"] = response.status
    except Exception as exc:  # expected: proxy dead / offline
        result["reachable"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


class socket_guard:
    """Block every outbound socket connection in this process (offline proof).

    Installed after the network probe and before the encoder is built, so the whole
    model-load / index-build / query path must run with no network access at all.
    """

    def __enter__(self) -> socket_guard:
        import socket

        self._originals = (
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.create_connection,
        )

        def blocked(*_args: Any, **_kwargs: Any) -> Any:
            raise ConnectionError("E02 offline guard: outbound network blocked")

        socket.socket.connect = blocked  # type: ignore[method-assign]
        socket.socket.connect_ex = blocked  # type: ignore[method-assign]
        socket.create_connection = blocked  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: Any) -> None:
        import socket

        (
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.create_connection,
        ) = self._originals


def _versions() -> dict[str, str]:
    out = {"python": sys.version.split()[0], "platform": sys.platform}
    for name in ("numpy", "tokenizers", "model2vec", "onnxruntime", "huggingface-hub"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = "absent"
    return out


def _git_identity() -> dict[str, str]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=WORKTREE, capture_output=True, text=True, check=False
        )
        return proc.stdout.strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "short": run("rev-parse", "--short", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
    }


# ---------------------------------------------------------------------------
# Encoders (CPU only, model files resolved locally)
# ---------------------------------------------------------------------------


def _l2_normalize(matrix: Any) -> Any:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (matrix / norms).astype(np.float32)


class Model2VecEncoder:
    """model2vec static embedding model (token embeddings only, no attention)."""

    def __init__(self, model_dir: Path) -> None:
        import model2vec

        self.model = model2vec.StaticModel.from_pretrained(str(model_dir))

    def encode(self, texts: list[str]) -> Any:
        import numpy as np

        vectors = np.asarray(self.model.encode(list(texts)), dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        return _l2_normalize(vectors)


class OnnxTransformerEncoder:
    """Transformer encoder via onnxruntime + tokenizers (mean pooling, L2)."""

    max_length = 256
    batch_size = 16

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=self.max_length)
        self.session = onnxruntime.InferenceSession(
            str(model_dir / "onnx" / "model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.output_name = self.session.get_outputs()[0].name

    def _encode_batch(self, texts: list[str]) -> Any:
        import numpy as np

        self.tokenizer.enable_padding()
        encoded = self.tokenizer.encode_batch(list(texts))
        input_ids = np.asarray([e.ids for e in encoded], dtype=np.int64)
        attention = np.asarray([e.attention_mask for e in encoded], dtype=np.int64)
        feed: dict[str, Any] = {"input_ids": input_ids, "attention_mask": attention}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        hidden: Any = self.session.run([self.output_name], feed)[0]
        mask: Any = attention.astype(np.float32)[:, :, None]
        pooled = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        return np.asarray(pooled, dtype=np.float32)

    def encode(self, texts: list[str]) -> Any:
        import numpy as np

        chunks = [
            self._encode_batch(texts[start : start + self.batch_size])
            for start in range(0, len(texts), self.batch_size)
        ]
        return _l2_normalize(np.vstack(chunks))


def build_encoder(encoder: str, model_dir: Path) -> Any:
    spec = MODEL_SPECS[encoder]
    if spec["kind"] == "model2vec":
        return Model2VecEncoder(model_dir / encoder)
    return OnnxTransformerEncoder(model_dir / encoder)


# ---------------------------------------------------------------------------
# Corpus: admissible rows + document text
# ---------------------------------------------------------------------------


def admissible_rows(semantic: Any, home: Path, project_id: str | None) -> list[dict[str, Any]]:
    """Same Phase-7 hard filters the FTS path applies in SQL (comparable pool)."""
    rows = []
    for row in semantic.list_memories(home):
        if semantic._row_passes_filters(row, project_id=project_id, include_history=False):
            rows.append(row)
    return rows


def document_text(semantic: Any, home: Path, row: dict[str, Any]) -> str:
    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    body = semantic._body_text(home, row)
    return "\n".join(part for part in (title, summary, body) if part).strip()


# ---------------------------------------------------------------------------
# Ranking arms
# ---------------------------------------------------------------------------


def _contribution_rows(
    semantic: Any, home: Path, text: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply the product's candidate-contribution stage when it is exposed.

    The corrected decision stage (S2) drops candidates whose query terms are not
    confirmed by the candidate's own headline / corpus rarity; retrieval alone does
    not decide injection any more. Absent API -> unchanged rows (fail open).
    """
    plan_fn = getattr(semantic, "query_match_plan", None)
    filter_fn = getattr(semantic, "contribution_filter", None)
    if plan_fn is None or filter_fn is None or not rows:
        return rows
    try:
        return list(filter_fn(rows, plan_fn(home, text)))
    except Exception:
        return rows


def lexical_retrieve(
    autoinject: Any,
    semantic: Any,
    cascade: Any,
    home: Path,
    text: str,
    *,
    project_id: str | None,
) -> tuple[list[dict[str, Any]], str]:
    """Mirror of autoinject's corrected retrieval chain.

    retrieve -> contribution -> focused retry -> narrowed retry, i.e. the same
    sequence `prepare_injection` runs, so the ranking diagnostic uses the production
    candidate order and the production contribution rule. Returns
    (rows in production order, query_mode).
    """
    proj_filter = project_id if project_id and project_id not in ("default", "unknown") else None
    query_mode = "idf"

    def one(query: str) -> list[dict[str, Any]]:
        result = cascade.retrieve(
            home, query, project_id=proj_filter, top_k=MAX_CANDIDATES, lane="semantic"
        )
        found = [
            m.raw_row if m.raw_row else (semantic._row(home, m.memory_id) or {})
            for m in result.matches
        ]
        if proj_filter is not None:
            unscoped = cascade.retrieve(
                home, query, project_id=None, top_k=MAX_CANDIDATES, lane="semantic"
            )
            supplement = [
                m.raw_row if m.raw_row else (semantic._row(home, m.memory_id) or {})
                for m in unscoped.matches
            ]
            seen = {str(r.get("memory_id")) for r in found}
            found.extend(
                r for r in supplement if r.get("memory_id") and str(r["memory_id"]) not in seen
            )
        return [dict(r) for r in found]

    def contributing(query: str) -> list[dict[str, Any]]:
        return _contribution_rows(semantic, home, query, one(query))

    rows = contributing(text)
    focused = autoinject._focused_query_text(text, project_id)
    if not rows and focused is not None:
        rows = contributing(focused)
        if rows:
            query_mode = "idf_focused"
    if not rows:
        narrowed_fn = getattr(autoinject, "_narrowed_query_text", None)
        narrowed = narrowed_fn(home, focused or text) if narrowed_fn is not None else None
        if narrowed is not None:
            rows = contributing(narrowed)
            if rows:
                query_mode = "idf_narrowed"
    return rows[:MAX_CANDIDATES], query_mode


def rrf_fuse(
    ranked_lists: list[list[dict[str, Any]]], *, top_k: int
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion; ties broken by lexical rank then memory id."""
    fused: dict[str, dict[str, Any]] = {}
    for arm_index, ranked in enumerate(ranked_lists):
        for rank, row in enumerate(ranked):
            mid = str(row.get("memory_id"))
            entry = fused.setdefault(
                mid, {"row": dict(row), "score": 0.0, "first_ranks": [10**9, 10**9]}
            )
            entry["score"] += 1.0 / (RRF_K + rank + 1)
            entry["first_ranks"][arm_index] = rank
    ordered = sorted(
        fused.values(),
        key=lambda e: (-e["score"], tuple(e["first_ranks"]), e["row"].get("memory_id")),
    )
    out = []
    for entry in ordered[:top_k]:
        row = dict(entry["row"])
        row["_score"] = float(entry["score"])
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Production decision tail (mirror of autoinject.prepare_injection post-retrieval)
# ---------------------------------------------------------------------------


def production_tail(
    autoinject: Any,
    semantic: Any,
    freshness: Any,
    home: Path,
    intent: Any,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Mirror of autoinject's post-retrieval tail, applied to any arm's ranking.

    Mirrored (not imported) because the production function performs its own
    retrieval; the lexical arm runs the real `prepare_injection` as well so the
    mirror is validated against production in the same run. The ROI/token-cost
    stage is reported (`roi_dropped_ids`) but not applied -- it is calibrated to the
    product's lexical score scale and would otherwise be a scale artifact for the
    dense and RRF arms (see the comment at its loop).
    """
    def out(
        injected: bool,
        reason: str | None,
        selected: list[str],
        tokens: int,
        stage: str,
        roi_dropped_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "injected": injected,
            "reason": reason,
            "selected_ids": selected,
            "tokens": tokens,
            "stage": stage,
            "roi_dropped_ids": roi_dropped_ids or [],
        }

    admitted = autoinject._valid_candidates(intent, rows)
    if not admitted:
        return out(False, "NO_RELEVANT_MEMORY", [], 0, "VALIDITY")
    fresh_valid: list[dict[str, Any]] = []
    for row in admitted:
        try:
            memory_id = str(row.get("memory_id") or "")
            source_rows = semantic._sources(home, memory_id)
            source = next((item for item in source_rows if item.get("path")), None)
            repo_root = (source or {}).get("repo_id") or intent.cwd or home
            state = freshness.resolve(home, memory_id, repo_root).get("state", freshness.UNKNOWN)
            if state in {freshness.STALE, freshness.SOURCE_MISSING}:
                continue
            enriched = dict(row)
            enriched["_freshness_state"] = state
            fresh_valid.append(enriched)
        except Exception:
            return out(False, "BRAIN_UNAVAILABLE", [], 0, "FRESHNESS")
    if not fresh_valid:
        return out(False, "NO_RELEVANT_MEMORY", [], 0, "FRESHNESS")
    role_rows = autoinject._role_filter(home, fresh_valid, intent.role_profile)
    if not role_rows:
        return out(False, "NO_RELEVANT_MEMORY", [], 0, "ROLE")
    items = autoinject._build_items(home, role_rows, lane=intent.lane)
    delivered = autoinject._delivered_keys(home, intent.session_id, intent.branch_id)
    fresh = [
        item
        for item in items
        if (item.memory_id, item.version, autoinject.item_canonical_hash(item)) not in delivered
    ]
    if not fresh:
        return out(False, "ALREADY_DELIVERED", [i.memory_id for i in items], 0, "DELIVERED")
    if fresh[0].status is autoinject.MemoryItemStatus.CONTRADICTED:
        return out(
            False, "CONTRADICTORY_UNRESOLVED", [i.memory_id for i in fresh], 0, "CONTRADICTED"
        )
    cfg = autoinject.load_config(home)
    active_budget = (
        autoinject.AutoInjectConfig(
            target_tokens=cfg.delta_target_tokens, hard_cap_tokens=cfg.delta_hard_cap_tokens
        )
        if intent.is_delta
        else cfg
    )
    row_by_id = {str(r.get("memory_id") or ""): r for r in role_rows}
    # The ROI stage (`p_need * value < token_cost_ratio`) is calibrated to the
    # product's lexical score scale (values ~0.5-1.0). Dense cosine and RRF scores
    # live on a different scale, so applying it here would reject every
    # dense/RRF candidate for scale reasons rather than ranking reasons. It is
    # therefore REPORTED (`roi_dropped_ids`) but not applied to the arm decisions;
    # the lexical arm's authoritative decision is the real `prepare_injection`.
    roi_dropped: list[str] = []
    for item in fresh:
        row = row_by_id.get(item.memory_id, {})
        p_need = row.get("_p_need")
        if p_need is None:
            try:
                from second_brain import reconsolidation

                base = reconsolidation.compute_base_level_activation(Path(home), item.memory_id)
                p_need = (
                    0.5
                    if base <= -10.0
                    else reconsolidation.compute_p_need(Path(home), item.memory_id)
                )
            except Exception:
                p_need = 0.5
        p_need = float(p_need)
        trust = 1.0
        try:
            trust = semantic._trust_score(row, semantic._DEFAULT_RETRIEVAL_CONFIG.weights)
        except Exception:
            trust = 1.0
        if row.get("_bm25_normalized") is not None:
            relevance = float(row["_bm25_normalized"])
        elif row.get("_score") is not None:
            relevance = float(row["_score"])
        elif row.get("_bm25") is not None:
            relevance = float(row["_bm25"])
        else:
            relevance = 1.0
        value = float(trust) * float(relevance)
        item_text = autoinject._render_packet_text([item], intent.project_id, lane=intent.lane)
        item_tokens = autoinject.token_estimate(item_text, home=home)
        token_cost_ratio = item_tokens / max(1, active_budget.target_tokens)
        if p_need * value < token_cost_ratio:
            roi_dropped.append(item.memory_id)
    retained = list(fresh)
    fit = autoinject._fit_budget(
        retained, intent.project_id, active_budget, home=home, lane=intent.lane
    )
    if fit is None:
        return out(
            False,
            "CONTEXT_PRESSURE",
            [i.memory_id for i in retained],
            0,
            "BUDGET",
            roi_dropped,
        )
    selected, _ids_only = fit
    text = autoinject._render_packet_text(selected, intent.project_id, lane=intent.lane)
    return out(
        True,
        None,
        [i.memory_id for i in selected],
        autoinject.token_estimate(text, home=home),
        "OK",
        roi_dropped,
    )


def gate_passes(scores: list[float], gate: Any, *, floor_override: float | None = None) -> bool:
    """Same shape as hybrid_retrieval.Cascade._gate_passes (score floor + gap)."""
    if not scores:
        return False
    floor = gate.abs_floor if floor_override is None else floor_override
    if scores[0] < floor:
        return False
    return len(scores) == 1 or (scores[0] - scores[1]) >= gate.gap_min


# ---------------------------------------------------------------------------
# Child: measure one arm in its own fresh process
# ---------------------------------------------------------------------------


def child_main(args: argparse.Namespace) -> int:
    t_start = time.perf_counter()
    arm, encoder = args.arm, args.encoder
    home = Path(args.corpus)
    cases_file = Path(args.cases)
    cases = _load_cases(cases_file)
    cases_sha256 = _sha256_file(cases_file)

    from second_brain import autoinject, freshness, hybrid_retrieval, semantic

    import_ms = (time.perf_counter() - t_start) * 1000.0
    ram: dict[str, Any] = {"after_import": process_memory()}

    dense = None
    model_load_ms = 0.0
    index_build_ms = 0.0
    index_rows = 0
    dense_rows: list[dict[str, Any]] = []
    dense_matrix: Any = None
    offline_probe = network_probe()
    guard = socket_guard() if encoder is not None else None
    if guard is not None:
        guard.__enter__()
    try:
        if encoder is not None:
            t = time.perf_counter()
            dense = build_encoder(encoder, Path(args.model_dir))
            model_load_ms = (time.perf_counter() - t) * 1000.0
            ram["after_model_load"] = process_memory()
            t = time.perf_counter()
            # Union pool: production always supplements the scoped search with the
            # unscoped one, so the admissible candidate union is the unscoped set
            # (the project rule is enforced again by _valid_candidates in the tail).
            dense_rows = admissible_rows(semantic, home, None)
            dense_matrix = dense.encode([document_text(semantic, home, r) for r in dense_rows])
            index_rows = len(dense_rows)
            index_build_ms = (time.perf_counter() - t) * 1000.0
            ram["after_index_build"] = process_memory()
    except BaseException:
        if guard is not None:
            guard.__exit__()
        raise

    cascade = hybrid_retrieval.HybridCascadeRetriever()
    gate = semantic.load_retrieval_config(home).gate

    def dense_rank(text: str, project_id: str | None, top_k: int) -> list[dict[str, Any]]:
        import numpy as np

        assert dense is not None and dense_matrix is not None
        vector = dense.encode([text])[0]
        scores = dense_matrix @ vector
        order = np.argsort(-scores, kind="stable")
        out = []
        for index in order[:top_k]:
            row = dict(dense_rows[int(index)])
            row["_score"] = float(scores[int(index)])
            out.append(row)
        return out

    def lexical_rank(text: str, project_id: str | None, top_k: int) -> list[dict[str, Any]]:
        rows, _mode = lexical_retrieve(
            autoinject, semantic, cascade, home, text, project_id=project_id
        )
        return rows[:top_k]

    def arm_rank(text: str, project_id: str | None, top_k: int) -> list[dict[str, Any]]:
        if arm == "lexical":
            return lexical_rank(text, project_id, top_k)
        if arm == "dense":
            return dense_rank(text, project_id, top_k)
        lexical_deep = lexical_rank(text, project_id, MAX_CANDIDATES)
        dense_deep = dense_rank(text, project_id, MAX_CANDIDATES)
        return rrf_fuse([lexical_deep, dense_deep], top_k=top_k)

    case_results: list[dict[str, Any]] = []
    latencies: dict[str, list[float]] = {
        "rank": [],
        "decision": [],
        "production": [],
        "encode_query": [],
        "tail": [],
    }
    for case in cases:
        intent = autoinject.RetrievalIntent(
            task_text=case["prompt"],
            project_id=args.project or None,
            agent_id="primary",
            role_profile="worker",
            session_id=f"e02-{arm}-{case['id']}",
            lane="semantic",
        )
        entry: dict[str, Any] = {
            "id": case["id"],
            "category": case["category"],
            "expect": list(case["expect"]),
        }
        t = time.perf_counter()
        primary_ranked = arm_rank(case["prompt"], args.project or None, MAX_CANDIDATES)
        entry["rank_ms"] = round((time.perf_counter() - t) * 1000.0, 3)
        entry["top_ids"] = [str(r.get("memory_id")) for r in primary_ranked]
        entry["top_scores"] = [round(float(r.get("_score") or 0.0), 6) for r in primary_ranked]

        if arm == "lexical":
            t = time.perf_counter()
            decision = autoinject.prepare_injection(
                home, intent, random_fn=lambda: 1.0, seed=None
            )
            entry["production_ms"] = round((time.perf_counter() - t) * 1000.0, 3)
            entry["production"] = {
                "injected": decision.decision.value == "INJECT",
                "reason": decision.reason.value if decision.reason is not None else None,
                "selected_ids": list(decision.selected_ids),
                "tokens": decision.packet_token_size or 0,
            }
            entry["decision"] = dict(entry["production"], source="production")
        tail = production_tail(autoinject, semantic, freshness, home, intent, primary_ranked)
        entry["tail_mirror"] = tail
        if arm != "lexical":
            entry["decision"] = {
                "injected": tail["injected"] and gate_passes(entry["top_scores"], gate),
                "reason": None if tail["injected"] else tail["reason"],
                "selected_ids": tail["selected_ids"],
                "tokens": tail["tokens"],
                "source": "gate+mirror",
            }
        case_results.append(entry)

    # Warm latency: repetitions of the arm's retrieval, encode and decision paths.
    reps = max(1, args.reps)
    gate_cfg = gate

    def arm_decision(text: str, project_id: str | None) -> dict[str, Any]:
        rows = arm_rank(text, project_id, MAX_CANDIDATES)
        scores = [float(r.get("_score") or 0.0) for r in rows]
        intent_ = autoinject.RetrievalIntent(
            task_text=text,
            project_id=project_id,
            agent_id="primary",
            role_profile="worker",
            session_id="e02-lat",
            lane="semantic",
        )
        t_tail = time.perf_counter()
        tail = production_tail(autoinject, semantic, freshness, home, intent_, rows)
        latencies["tail"].append((time.perf_counter() - t_tail) * 1000.0)
        tail["gate_passed"] = gate_passes(scores, gate_cfg)
        return tail

    for _ in range(2):  # warmup
        for case in cases:
            arm_decision(case["prompt"], args.project or None)
    if dense is not None:
        for _ in range(reps):
            for case in cases:
                t = time.perf_counter()
                dense.encode([case["prompt"]])
                latencies.setdefault("encode_query", []).append((time.perf_counter() - t) * 1000.0)
    for _ in range(reps):
        for case in cases:
            t = time.perf_counter()
            arm_rank(case["prompt"], args.project or None, MAX_CANDIDATES)
            latencies["rank"].append((time.perf_counter() - t) * 1000.0)
    for _ in range(reps):
        for case in cases:
            t = time.perf_counter()
            arm_decision(case["prompt"], args.project or None)
            latencies["decision"].append((time.perf_counter() - t) * 1000.0)
    if arm == "lexical":
        for _ in range(reps):
            case = cases[0]
            intent_ = autoinject.RetrievalIntent(
                task_text=case["prompt"],
                project_id=args.project or None,
                agent_id="primary",
                role_profile="worker",
                session_id="e02-lat-prod",
                lane="semantic",
            )
            t = time.perf_counter()
            autoinject.prepare_injection(home, intent_, random_fn=lambda: 1.0, seed=None)
            latencies["production"].append((time.perf_counter() - t) * 1000.0)

    def stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {}
        ordered = sorted(values)
        index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
        return {
            "median": round(statistics.median(ordered), 3),
            "p95": round(ordered[index], 3),
            "min": round(ordered[0], 3),
            "max": round(ordered[-1], 3),
        }

    ram["end"] = process_memory()
    if guard is not None:
        guard.__exit__()
    encoder_info: dict[str, Any] = {}
    if dense is not None:
        session = getattr(dense, "session", None)
        encoder_info = {
            "class": type(dense).__name__,
            "batch_size": getattr(dense, "batch_size", None),
            "max_length": getattr(dense, "max_length", None),
            "dim": dense.encode(["dimension probe"]).shape[1],
            "providers": (
                list(session.get_providers()) if session is not None else ["cpu-only (numpy)"]
            ),
        }
    result = {
        "arm": arm,
        "encoder": encoder,
        "case_file": {"path": str(cases_file), "sha256": cases_sha256, "count": len(cases)},
        "encoder_info": encoder_info,
        "network_probe": offline_probe,
        "offline_guard": {"sockets_blocked_during_encode": guard is not None},
        "project_id": args.project or None,
        "reps": reps,
        "git": _git_identity(),
        "versions": _versions(),
        "phases_ms": {
            "module_startup": round((t_start - PROCESS_START) * 1000.0, 2),
            "import": round(import_ms, 2),
            "model_load": round(model_load_ms, 2),
            "index_build": round(index_build_ms, 2),
        },
        "index_rows": index_rows,
        "ram": ram,
        "latency_ms": {key: stats(value) for key, value in latencies.items()},
        "cases": case_results,
    }
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"[child] {arm}" + (f" ({encoder})" if encoder else "")
        + f" import={result['phases_ms']['import']}ms"
        + (f" model={model_load_ms:.0f}ms index={index_build_ms:.0f}ms" if encoder else "")
        + f" peak={ram['end'].get('peak_working_set_mib')}MiB",
        flush=True,
    )
    return 0


# ---------------------------------------------------------------------------
# Aggregation (parent)
# ---------------------------------------------------------------------------


def recall_at(entries: list[dict[str, Any]], key: str, k: int) -> dict[str, Any]:
    positives = [e for e in entries if e["expect"]]
    hits = sum(1 for e in positives if set(e[key][:k]) & set(e["expect"]))
    return {
        "hits": hits,
        "total": len(positives),
        "recall": round(hits / len(positives), 4) if positives else None,
        "per_case": {e["id"]: bool(set(e[key][:k]) & set(e["expect"])) for e in positives},
    }


def false_candidate_rate(entries: list[dict[str, Any]], key: str, k: int) -> dict[str, Any]:
    negatives = [e for e in entries if not e["expect"]]
    fired = [e["id"] for e in negatives if e[key][:k]]
    return {
        "fired": len(fired),
        "total": len(negatives),
        "rate": round(len(fired) / len(negatives), 4) if negatives else None,
        "cases": fired,
    }


def decision_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [e for e in entries if e["expect"]]
    negatives = [e for e in entries if not e["expect"]]
    delivered = [
        e["id"]
        for e in positives
        if e["decision"]["injected"] and set(e["decision"]["selected_ids"]) & set(e["expect"])
    ]
    false_fired = [e["id"] for e in negatives if e["decision"]["injected"]]
    tokens = [e["decision"]["tokens"] for e in entries if e["decision"]["tokens"]]
    return {
        "delivered_recall": {
            "hits": len(delivered),
            "total": len(positives),
            "recall": round(len(delivered) / len(positives), 4) if positives else None,
            "per_case": {e["id"]: e["id"] in delivered for e in positives},
        },
        "false_candidate": {
            "fired": len(false_fired),
            "total": len(negatives),
            "rate": round(len(false_fired) / len(negatives), 4) if negatives else None,
            "cases": false_fired,
        },
        "injected_tokens": {
            "median": round(statistics.median(tokens), 1) if tokens else 0,
            "max": max(tokens) if tokens else 0,
            "per_case": {e["id"]: e["decision"]["tokens"] for e in entries},
        },
        "decisions": {e["id"]: e["decision"] for e in entries},
    }


def _passes(scores: list[float], floor: float, gap: float) -> bool:
    if not scores or scores[0] < floor:
        return False
    return len(scores) == 1 or (scores[0] - scores[1]) >= gap


def _sweep_rows(
    entries: list[dict[str, Any]], floors: list[float], gap: float
) -> list[dict[str, Any]]:
    """Decision-level sweep: gate(floor, gap) AND the production tail for that arm.

    Production semantics: a failed gate means LOW_CONFIDENCE -> abstain, and the
    tail (validity/freshness/role/ROI/budget) sees the same candidate list, so the
    tail outcome is floor-independent and computed once per case.
    """
    positives = [e for e in entries if e["expect"]]
    negatives = [e for e in entries if not e["expect"]]
    case_tokens = {e["id"]: e["decision"]["tokens"] for e in entries}
    rows = []
    for floor in floors:
        delivered = [
            e["id"]
            for e in positives
            if e["tail_mirror"]["injected"]
            and _passes(e["top_scores"], floor, gap)
            and set(e["tail_mirror"]["selected_ids"]) & set(e["expect"])
        ]
        fired = [
            e["id"]
            for e in negatives
            if e["tail_mirror"]["injected"] and _passes(e["top_scores"], floor, gap)
        ]
        injected_ids = [*delivered, *fired]
        token_values = [case_tokens.get(case_id, 0) for case_id in injected_ids]
        rows.append(
            {
                "floor": round(floor, 6),
                "recall": round(len(delivered) / len(positives), 4) if positives else None,
                "false_rate": round(len(fired) / len(negatives), 4) if negatives else None,
                "delivered_ids": delivered,
                "false_ids": fired,
                "injected_tokens": {c: case_tokens.get(c, 0) for c in injected_ids},
                "injected_tokens_median": (
                    round(statistics.median(token_values), 1) if token_values else 0
                ),
            }
        )
    return rows


def threshold_sweep(entries: list[dict[str, Any]], gate: Any) -> dict[str, Any]:
    """Recall vs no-benefit false rate for every decision floor (two gate shapes)."""
    positives = [e for e in entries if e["expect"]]
    negatives = [e for e in entries if not e["expect"]]
    observed = [e["top_scores"][0] for e in entries if e["top_scores"]]
    floors = sorted({0.0, round(gate.abs_floor, 6), *(round(s, 6) for s in observed)})
    if observed:
        floors.append(round(max(observed) + 1e-6, 6))
    variants: dict[str, Any] = {}
    for name, gap in (("production_gate", gate.gap_min), ("threshold_only", 0.0)):
        rows = _sweep_rows(entries, floors, gap)
        zero_false = [r for r in rows if not r["false_ids"]]
        best_zero = (
            max(zero_false, key=lambda r: (r["recall"] or 0.0, r["floor"])) if zero_false else None
        )
        variants[name] = {
            "gap_min": gap,
            "rows": rows,
            "best_at_zero_false": best_zero,
            "at_production_floor": next(
                (r for r in rows if abs(r["floor"] - gate.abs_floor) < 1e-9), None
            ),
        }
    return {
        "variants": variants,
        "positive_top1": {
            e["id"]: (e["top_scores"][0] if e["top_scores"] else None) for e in positives
        },
        "negative_top1": {
            e["id"]: (e["top_scores"][0] if e["top_scores"] else None) for e in negatives
        },
        "tail_injected": {e["id"]: e["tail_mirror"]["injected"] for e in entries},
    }


def aggregate(child: dict[str, Any], gate: Any) -> dict[str, Any]:
    entries = child["cases"]
    out: dict[str, Any] = {
        "arm": child["arm"],
        "encoder": child["encoder"],
        "recall_at_k": {
            str(k): recall_at(entries, "top_ids", k) for k in (1, 2, 3, 5, 10)
        },
        "false_candidate_at_k": {
            str(k): false_candidate_rate(entries, "top_ids", k) for k in (1, 3, 10)
        },
        "decision": decision_stats(entries),
        "threshold_sweep": threshold_sweep(entries, gate),
        "phases_ms": child["phases_ms"],
        "index_rows": child["index_rows"],
        "spawn_wall_ms": child.get("spawn_wall_ms"),
        "encoder_info": child.get("encoder_info", {}),
        "network_probe": child.get("network_probe"),
        "offline_guard": child.get("offline_guard"),
        "ram": child["ram"],
        "latency_ms": child["latency_ms"],
        "versions": child["versions"],
        "git": child["git"],
    }
    if child["arm"] == "lexical":
        agreement = 0
        total = 0
        for entry in entries:
            prod = entry.get("production")
            mirror = entry.get("tail_mirror")
            if prod is None or mirror is None:
                continue
            total += 1
            if (
                prod["injected"] == mirror["injected"]
                and set(prod["selected_ids"]) == set(mirror["selected_ids"])
            ):
                agreement += 1
        out["tail_mirror_vs_production"] = {"agree": agreement, "total": total}
    return out


def verdict_block(arms: dict[str, Any]) -> dict[str, Any]:
    """Adoption rule from the S2 contract, evaluated on the dev split.

    Rule: a semantic component ships only if it beats the lexical baseline's
    delivered recall by >= 5 points at equal-or-better no-benefit abstention, stays
    within 1024 MiB resident, is CPU-only and offline. If the lexical baseline's
    recall is > 95%, no semantic component can qualify.
    """
    block: dict[str, Any] = {"rule": VALIDATION_RULE, "ram_budget_mib": RAM_BUDGET_MIB, "arms": {}}
    lex = arms.get("lexical")
    if lex is None:
        return block
    lex_recall = lex["decision"]["delivered_recall"]["recall"]
    lex_false = lex["decision"]["false_candidate"]["rate"]
    block["lexical"] = {
        "delivered_recall": lex_recall,
        "false_candidate_rate": lex_false,
        "recall_at_1": lex["recall_at_k"]["1"]["recall"],
        "recall_at_10": lex["recall_at_k"]["10"]["recall"],
        "source": "autoinject.prepare_injection (production decision)",
        "recall_over_95pct_disqualifies_all": bool(lex_recall is not None and lex_recall > 0.95),
    }
    for name, arm in arms.items():
        if name == "lexical":
            continue
        variants = arm["threshold_sweep"]["variants"]
        best: dict[str, Any] | None = None
        for variant_name, variant in variants.items():
            rows = [
                r
                for r in variant["rows"]
                if lex_false is None
                or (r["false_rate"] is not None and r["false_rate"] <= lex_false)
            ]
            if not rows:
                continue
            candidate = max(rows, key=lambda r: (r["recall"] or 0.0, r["floor"]))
            if best is None or (candidate["recall"] or 0.0) > (best["recall"] or 0.0):
                best = dict(candidate, variant=variant_name, gap_min=variant["gap_min"])
        peak = (arm["ram"].get("end") or {}).get("peak_working_set_mib")
        info = arm.get("encoder_info", {})
        block["arms"][name] = {
            "best_recall_within_lexical_false_budget": best["recall"] if best else None,
            "best_floor": best["floor"] if best else None,
            "best_variant": best["variant"] if best else None,
            "best_gap_min": best["gap_min"] if best else None,
            "delta_vs_lexical": (
                round((best["recall"] or 0.0) - lex_recall, 4)
                if best is not None and lex_recall is not None
                else None
            ),
            "gate_false_rate_at_best": best["false_rate"] if best else None,
            "injected_tokens_median_at_best": best["injected_tokens_median"] if best else None,
            "injected_tokens_at_best": best["injected_tokens"] if best else None,
            "peak_working_set_mib": peak,
            "within_ram_budget": peak is not None and peak <= RAM_BUDGET_MIB,
            "cpu_only": (info.get("providers") in (["CPUExecutionProvider"], ["cpu-only (numpy)"]))
            if info
            else None,
            "recall_at_10": arm["recall_at_k"]["10"]["recall"],
        }
        entry = block["arms"][name]
        entry["qualifies"] = bool(
            best is not None
            and lex_recall is not None
            and (best["recall"] or 0.0) - lex_recall >= 0.05
            and entry["within_ram_budget"]
            and entry["cpu_only"] is not False
            and not block["lexical"]["recall_over_95pct_disqualifies_all"]
        )
    block["any_qualifies"] = any(a["qualifies"] for a in block["arms"].values())
    return block


def prefetch(model_dir: Path) -> int:
    model_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"model_dir": str(model_dir), "models": {}}
    for name, spec in MODEL_SPECS.items():
        target = model_dir / name
        target.mkdir(parents=True, exist_ok=True)
        if spec["kind"] == "model2vec":
            if not (target / "model.safetensors").is_file():
                from model2vec import StaticModel

                model = StaticModel.from_pretrained(spec["repo"])
                model.save_pretrained(str(target))
        else:
            from huggingface_hub import hf_hub_download

            for filename in spec["files"]:
                local = target / filename
                local.parent.mkdir(parents=True, exist_ok=True)
                if not local.is_file():
                    shutil.copy2(
                        hf_hub_download(repo_id=spec["repo"], filename=filename), local
                    )
        files = sorted(p for p in target.rglob("*") if p.is_file())
        manifest["models"][name] = {
            "repo": spec["repo"],
            "kind": spec["kind"],
            "path": str(target),
            "files": [
                {
                    "name": p.relative_to(target).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": _sha256_file(p),
                }
                for p in files
            ],
            "total_bytes": sum(p.stat().st_size for p in files),
        }
    manifest["versions"] = _versions()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "models.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({k: v["total_bytes"] for k, v in manifest["models"].items()}, indent=2))
    return 0


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_path = Path(args.cases)
    cases = _load_cases(cases_path)
    # Freeze the case file for this run: children read the snapshot, so a concurrent
    # edit of the dev split (or of whatever --cases points at) cannot make arms see
    # different case sets. Both hashes are recorded in the results.
    cases_source_sha256 = _sha256_file(cases_path)
    cases_snapshot = out_dir / "cases.used.jsonl"
    shutil.copy2(cases_path, cases_snapshot)
    cases_sha256 = _sha256_file(cases_snapshot)
    print(
        f"[run] cases: {len(cases)} from {cases_path} "
        f"({cases_source_sha256[:16]}) -> {cases_snapshot.name} ({cases_sha256[:16]})",
        flush=True,
    )
    manifest = _load_matched_arms()
    snapshot_root = Path(tempfile.mkdtemp(prefix="v3-e02-snap-"))
    base = snapshot_root / "base"
    snapshot = manifest.snapshot_corpus(CANONICAL, base)
    print(f"[run] snapshot: {json.dumps(snapshot)}", flush=True)

    child_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONHOME", "PYTHONPATH")
    }
    child_env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            # A dead proxy: any real HTTP attempt fails instead of silently online.
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
        }
    )

    children: list[dict[str, Any]] = []
    spawn_wall: dict[str, float] = {}
    for arm_spec in args.only or list(ARMS):
        arm, _, encoder = arm_spec.partition(":")
        arm_dir = snapshot_root / arm_spec.replace(":", "-")
        shutil.copytree(base, arm_dir)
        out_file = out_dir / f"child_{arm_spec.replace(':', '-')}.json"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "child",
            "--arm",
            arm,
            "--corpus",
            str(arm_dir),
            "--cases",
            str(cases_snapshot),
            "--out",
            str(out_file),
            "--reps",
            str(args.reps),
            "--project",
            args.project,
            "--model-dir",
            str(Path(args.model_dir)),
        ]
        if encoder:
            cmd += ["--encoder", encoder]
        t = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, env=child_env, check=False)
        wall = (time.perf_counter() - t) * 1000.0
        if proc.returncode != 0:
            print(
                f"[run] {arm_spec} FAILED rc={proc.returncode}\n"
                f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
            )
            continue
        spawn_wall[arm_spec] = round(wall, 1)
        child = json.loads(out_file.read_text(encoding="utf-8"))
        child["spawn_wall_ms"] = round(wall, 1)
        children.append(child)
        print(f"[run] {arm_spec} ok wall={wall:.0f}ms", flush=True)
        shutil.rmtree(arm_dir, ignore_errors=True)

    gate = None
    sys.path.insert(0, str(WORKTREE / "src"))
    from second_brain import semantic as semantic_module

    gate = semantic_module.load_retrieval_config(base).gate

    arms = {
        f"{c['arm']}:{c['encoder']}" if c["encoder"] else c["arm"]: aggregate(c, gate)
        for c in children
    }
    case_sets = {c["case_file"]["sha256"] for c in children}
    case_counts = {c["case_file"]["count"] for c in children}
    case_set_consistent = len(case_sets) == 1 and case_counts == {len(cases)}
    if not case_set_consistent:
        print(f"[run] WARNING inconsistent case sets: {case_sets} counts {case_counts}")
    results = {
        "experiment": "v3-s2-e02-semantic",
        "date": time.strftime("%Y-%m-%d"),
        "git": _git_identity(),
        "source_corpus": snapshot,
        "source_fingerprints": {
            name: _sha256_file(WORKTREE / "src" / "second_brain" / f"{name}.py")
            for name in (
                "autoinject",
                "semantic",
                "hybrid_retrieval",
                "freshness",
                "reconsolidation",
            )
        },
        "script_fingerprint": _sha256_file(Path(__file__).resolve()),
        "dev_cases": {
            "path": str(cases_path),
            "source_sha256": cases_source_sha256,
            "snapshot": str(cases_snapshot),
            "sha256": cases_sha256,
            "case_set_consistent": case_set_consistent,
            "child_case_sets": sorted(case_sets),
            "cases": [c["id"] for c in cases],
            "memory_needing": [c["id"] for c in cases if c["expect"]],
            "no_benefit": [c["id"] for c in cases if not c["expect"]],
            "heldout_used": False,
        },
        "settings": {
            "project_id": args.project,
            "role_profile": "worker",
            "max_candidates": MAX_CANDIDATES,
            "rrf_k": RRF_K,
            "gate": {
                "abs_floor": gate.abs_floor,
                "gap_min": gate.gap_min,
                "lane_floor_semantic": gate.lane_floors.get("semantic"),
            },
            "offline_env": {
                k: child_env[k]
                for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HTTP_PROXY")
            },
            "model_dir": str(Path(args.model_dir)),
            "reps": args.reps,
            "dependency_policy": (
                "encoder libraries installed into the worktree venv only for the "
                "experiment; pyproject.toml untouched (no mandatory dependency added)"
            ),
            "note": "dev split only; held-out never opened",
        },
        "encoders": MODEL_SPECS,
        "versions": _versions(),
        "arms": arms,
        "verdict": verdict_block(arms),
        "spawn_wall_ms": spawn_wall,
    }
    models_manifest = OUT_DIR / "models.manifest.json"
    if models_manifest.is_file():
        results["model_files"] = json.loads(models_manifest.read_text(encoding="utf-8"))["models"]
    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[run] wrote {results_path}")
    shutil.rmtree(snapshot_root, ignore_errors=True)
    return 0


def summarize(path: Path) -> int:
    """Render the arm comparison tables from an existing results.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"git {data['git']['short']} branch={data['git']['branch']}")
    corpus = data["source_corpus"]
    print(f"corpus db_sha256 {corpus['db_sha256'][:16]} memories={corpus['memories']}")
    cases = data["dev_cases"]
    print(f"dev cases {cases['sha256'][:16]} heldout_used={cases['heldout_used']}")
    header = (
        f"{'arm':22s} {'rec@1':>6s} {'rec@3':>6s} {'rec@10':>7s} "
        f"{'deliv':>6s} {'false':>6s} {'tok_med':>8s} {'peakMiB':>8s} "
        f"{'load_ms':>8s} {'idx_ms':>7s} {'rank_med':>9s} {'best_rec':>9s} {'best_floor':>10s}"
    )
    print(header)
    for name, arm in data["arms"].items():
        dec = arm["decision"]
        ram = (arm["ram"].get("end") or {}).get("peak_working_set_mib")
        phases = arm["phases_ms"]
        lat = arm["latency_ms"].get("rank", {})
        sweep_best = None
        for variant in arm["threshold_sweep"]["variants"].values():
            best = variant["best_at_zero_false"]
            if best and (sweep_best is None or (best["recall"] or 0) > (sweep_best["recall"] or 0)):
                sweep_best = best
        print(
            f"{name:22s} {arm['recall_at_k']['1']['recall']!s:>6s} "
            f"{arm['recall_at_k']['3']['recall']!s:>6s} {arm['recall_at_k']['10']['recall']!s:>7s} "
            f"{dec['delivered_recall']['recall']!s:>6s} {dec['false_candidate']['rate']!s:>6s} "
            f"{dec['injected_tokens']['median']!s:>8s} {ram!s:>8s} "
            f"{phases['model_load']:>8.1f} {phases['index_build']:>7.1f} "
            f"{lat.get('median')!s:>9s} "
            f"{sweep_best['recall'] if sweep_best else None!s:>9s} "
            f"{sweep_best['floor'] if sweep_best else None!s:>10s}"
        )
    print("\nper-case: id arm=top1_score/retrieved@10 (memory-needing cases only)")
    cases = data["dev_cases"]["memory_needing"]
    for case_id in cases:
        row = []
        for name, arm in data["arms"].items():
            sweep = arm["threshold_sweep"]
            score = sweep["positive_top1"].get(case_id)
            hit = arm["recall_at_k"]["10"]["per_case"].get(case_id)
            row.append(f"{name}={score}/{hit}")
        print(f"  {case_id:4s} {' '.join(row)}")
    print("\nper-case no-benefit: id arm=top1_score")
    for case_id in data["dev_cases"]["no_benefit"]:
        row = []
        for name, arm in data["arms"].items():
            score = arm["threshold_sweep"]["negative_top1"].get(case_id)
            row.append(f"{name}={score}")
        print(f"  {case_id:4s} {' '.join(row)}")
    print("\nverdict block:")
    print(json.dumps(data.get("verdict", {}), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("prefetch", help="download/verify local model files (one-time)")
    pf.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))

    parent = sub.add_parser("run", help="snapshot the corpus, run every arm in its own process")
    parent.add_argument("--out", default=str(OUT_DIR))
    parent.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parent.add_argument("--cases", default=str(DEV_CASES))
    parent.add_argument("--project", default="second-brain")
    parent.add_argument("--reps", type=int, default=5)
    parent.add_argument("--only", nargs="*", default=None)

    summary = sub.add_parser("summarize", help="render tables from a results.json")
    summary.add_argument("results", nargs="?", default=str(OUT_DIR / "results.json"))

    child = sub.add_parser("child", help="internal: measure one arm")
    child.add_argument("--arm", required=True)
    child.add_argument("--encoder", default=None)
    child.add_argument("--corpus", required=True)
    child.add_argument("--cases", default=str(DEV_CASES))
    child.add_argument("--out", required=True)
    child.add_argument("--project", default="second-brain")
    child.add_argument("--reps", type=int, default=5)
    child.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))

    args = parser.parse_args(argv)
    if args.command == "prefetch":
        return prefetch(Path(args.model_dir))
    if args.command == "run":
        return run(args)
    if args.command == "summarize":
        return summarize(Path(args.results))
    return child_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
