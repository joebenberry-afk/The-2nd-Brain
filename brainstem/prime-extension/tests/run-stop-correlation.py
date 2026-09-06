"""Run only named STOP fixtures; retain raw child output and true exit status."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

extension = Path(__file__).resolve().parents[1]
spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
artifacts = Path(spec["artifacts"]).resolve()
artifacts.mkdir(parents=True, exist_ok=True)
allowed = {"tests/stop-correlation.test.ts", "tests/stop-boundary.test.ts", "tests/wiring.test.ts"}
files = spec["files"]
if not files or any(name not in allowed for name in files):
    raise SystemExit("Unexpected fixture filename")
env = os.environ.copy()
for key in list(env):
    if key.startswith("SECOND_BRAIN_") or key.startswith("ORCHESTRATOR_"):
        del env[key]
env.update({"SECOND_BRAIN_HOME": str(artifacts / "home"), "STOP_CORRELATION_EVIDENCE": str(artifacts), "STOP_CORRELATION_BASELINE": "1" if spec.get("baseline") else "0"})
Path(env["SECOND_BRAIN_HOME"]).mkdir(exist_ok=True)
command = ["node", str(extension / "node_modules/vitest/vitest.mjs"), "run", *files, "--reporter=json", "--outputFile=" + str(artifacts / "vitest.json")]
baseline_copy = extension / "src/.stop-correlation-baseline.ts"
if spec.get("baseline"):
    # Exclusive creation protects unrelated untracked work at this path.
    snapshot = Path(spec["baseline_source"]).read_bytes()
    with baseline_copy.open("xb") as destination:
        destination.write(snapshot)
with (artifacts / "stdout.txt").open("wb") as stdout, (artifacts / "stderr.txt").open("wb") as stderr:
    try:
        child = subprocess.run(command, cwd=extension, env=env, stdout=stdout, stderr=stderr, timeout=180, check=False)
        code = child.returncode
        timeout = False
    except subprocess.TimeoutExpired:
        code = None
        timeout = True
    finally:
        if spec.get("baseline"):
            baseline_copy.unlink()
summary = {"command": command, "child_exit_code": code, "timed_out": timeout, "wrapper_alive_after_child": True, "artifacts": str(artifacts)}
report = artifacts / "vitest.json"
if report.exists():
    data = json.loads(report.read_text(encoding="utf-8"))
    summary.update({key: data.get(key) for key in ["numPassedTests", "numFailedTests", "numTotalTests"]})
summary["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts.iterdir() if p.is_file()}
(artifacts / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({key: summary[key] for key in ["child_exit_code", "timed_out", "wrapper_alive_after_child", "artifacts", "numPassedTests", "numFailedTests", "numTotalTests"] if key in summary}))
# The wrapper survives failure, records it, and propagates the actual child exit.
sys.exit(code if code is not None else 124)
