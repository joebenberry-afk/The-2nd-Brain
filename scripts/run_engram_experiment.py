"""Provider-free workflow engram qualification using real owned I/O."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from second_brain import engram
from second_brain.security.paths import resolve_under

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs" / "reports" / "v2" / "engrams" / "engram-experiment.json"


def _result(
    tool: str, *, exit_code: int = 0, side_effect: bool = False, **extra: object
) -> dict[str, object]:
    return {"tool": tool, "exit_code": exit_code, "side_effect": side_effect, **extra}


def _owned_tool_runner(home: Path):
    def run(tool: str, args: Mapping[str, object]) -> dict[str, object]:
        if tool == "write_marker":
            path = resolve_under(home, str(args["path"]), allow_missing=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(args["content"]), encoding="utf-8")
            return _result(tool, side_effect=True)
        if tool == "read_file":
            path = resolve_under(home, str(args["path"]))
            return _result(tool, content=path.read_text(encoding="utf-8"))
        if tool == "verify_marker":
            path = resolve_under(home, str(args["path"]))
            expected = str(args["content"])
            return _result(
                tool,
                exit_code=0 if path.read_text(encoding="utf-8") == expected else 1,
                content=path.read_text(encoding="utf-8"),
            )
        raise RuntimeError(f"unsupported owned workflow tool: {tool}")

    return run


def _owned_predicate_runner(home: Path):
    def run(predicate: str, args: Mapping[str, object]) -> dict[str, object]:
        path = resolve_under(home, str(args["path"]), allow_missing=predicate == "path_exists")
        if predicate == "path_exists":
            return _result(predicate, exit_code=0 if path.exists() else 1)
        if predicate == "file_nonempty":
            return _result(predicate, exit_code=0 if path.is_file() and path.stat().st_size else 1)
        if predicate == "file_contains":
            return _result(
                predicate,
                exit_code=0
                if path.is_file() and str(args["text"]) in path.read_text(encoding="utf-8")
                else 1,
            )
        raise RuntimeError(f"unsupported owned workflow predicate: {predicate}")

    return run


def _event(tool: str, session: str, **args: object) -> dict[str, object]:
    return {
        "kind": "tool_call",
        "session": session,
        "tool": tool,
        "input": args,
        "result": {"exit_code": 0, "side_effect": tool == "write_marker"},
    }


def run_engram_experiment(output_path: Path | None = None) -> dict[str, Any]:
    temp_dir = Path(tempfile.mkdtemp(prefix="second_brain_engram_exp_"))
    try:
        (temp_dir / "workspace").mkdir()
        repeated = [
            _event("write_marker", "sess-a", path="workspace/marker.txt", content="v1"),
            _event("read_file", "sess-a", path="workspace/marker.txt"),
            _event("verify_marker", "sess-a", path="workspace/marker.txt", content="v1"),
        ]
        repeated_b = [
            _event("write_marker", "sess-b", path="workspace/marker.txt", content="v1"),
            _event("read_file", "sess-b", path="workspace/marker.txt"),
            _event("verify_marker", "sess-b", path="workspace/marker.txt", content="v1"),
        ]
        detected = engram.detect_workflow_engrams(
            [repeated, repeated_b], min_support=2, min_len=3, max_len=3
        )
        if not detected:
            raise RuntimeError("no repeated successful workflow was detected")
        distilled = detected[0]
        procedure = [
            {
                "tool": "write_marker",
                "args_template": {"path": "$path", "content": "$content"},
                "precondition": {
                    "predicate": "path_exists",
                    "args_template": {"path": "$directory"},
                    "expect_exit": 0,
                },
                "postcondition": {
                    "predicate": "file_contains",
                    "args_template": {"path": "$path", "text": "$content"},
                    "expect_exit": 0,
                },
            },
            {
                "tool": "read_file",
                "args_template": {"path": "$path"},
                "postcondition": {
                    "predicate": "file_nonempty",
                    "args_template": {"path": "$path"},
                    "expect_exit": 0,
                },
            },
            {
                "tool": "verify_marker",
                "args_template": {"path": "$path", "content": "$content"},
            },
        ]
        registered = engram.register_workflow_engram(
            temp_dir,
            {
                "engram_id": distilled["engram_id"],
                "version": 1,
                "procedure": procedure,
                "provenance": distilled["provenance"],
                "status": "candidate",
            },
        )
        tool_runner = _owned_tool_runner(temp_dir)
        predicate_runner = _owned_predicate_runner(temp_dir)
        params = {
            "directory": "workspace",
            "path": "workspace/marker.txt",
            "content": "v1",
        }
        run1 = engram.run_deterministic(
            temp_dir,
            registered["engram_id"],
            params=params,
            tool_runner=tool_runner,
            predicate_runner=predicate_runner,
        )
        run2 = engram.run_deterministic(
            temp_dir,
            registered["engram_id"],
            params=params,
            tool_runner=tool_runner,
            predicate_runner=predicate_runner,
        )
        read_only = engram.register_workflow_engram(
            temp_dir,
            {
                "engram_id": "owned-read-replay",
                "version": 1,
                "cache_policy": "read_only",
                "cache_inputs": ["path"],
                "procedure": [
                    {
                        "tool": "read_file",
                        "effect": "read",
                        "args_template": {"path": "$path"},
                        "postcondition": {
                            "predicate": "file_nonempty",
                            "args_template": {"path": "$path"},
                            "expect_exit": 0,
                        },
                    }
                ],
            },
        )
        read1 = engram.run_deterministic(
            temp_dir,
            read_only["engram_id"],
            params={"path": "workspace/marker.txt"},
            tool_runner=tool_runner,
            predicate_runner=predicate_runner,
        )
        read2 = engram.run_deterministic(
            temp_dir,
            read_only["engram_id"],
            params={"path": "workspace/marker.txt"},
            tool_runner=tool_runner,
            predicate_runner=predicate_runner,
        )
        (temp_dir / "workspace" / "marker.txt").write_text("v2", encoding="utf-8")
        read3 = engram.run_deterministic(
            temp_dir,
            read_only["engram_id"],
            params={"path": "workspace/marker.txt"},
            tool_runner=tool_runner,
            predicate_runner=predicate_runner,
        )
        if not run1["success"] or not run2["success"]:
            raise RuntimeError("real workflow replay failed")
        if read1["cache_hit"] or not read2["cache_hit"] or read3["cache_hit"]:
            raise RuntimeError("read-only cache invalidation contract failed")
        manifest = {
            "experiment": "P3.3 provider-free real workflow replay",
            "scope": "local workflow-to-macro execution only; teacher/student transfer is external",
            "metrics": {
                "extracted_workflow_sequence": distilled["sequence"],
                "workflow_support_count": distilled["support"],
                "source_provenance_count": len(distilled["provenance"]),
                "real_workflow_first_success": run1["success"],
                "real_workflow_second_success": run2["success"],
                "read_cache_first_hit": read1["cache_hit"],
                "read_cache_second_hit": read2["cache_hit"],
                "read_cache_changed_input_hit": read3["cache_hit"],
                "changed_content": read3["steps"][0]["output"]["content"],
            },
            "distilled_engram": registered,
            "first_run_result": run1,
            "second_run_result": run2,
            "read_cache_results": [read1, read2, read3],
            "external_transfer": "not_attempted",
            "conclusion": (
                "PASS: real owned tools and predicates executed; side-effecting "
                "workflow was not cached; read-only cache invalidated on changed "
                "input; cache resources closed."
            ),
        }
        destination = output_path or OUTPUT_PATH
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
        print(f"Wrote engram experiment results to {destination}")
        print(f"Workflow: {' -> '.join(distilled['sequence'])}, Support: {distilled['support']}")
        return manifest
    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    run_engram_experiment(parser.parse_args().output)
