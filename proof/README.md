# v4.3 proof campaign

This directory is the auditable campaign harness for the v4.3 plan supplied at
`C:\Users\assas\Downloads\The_Second_Brain_v4_3_Proof_and_Validation_Test_Plan.md`.

The candidate currently has a verified C0/C1 Prime observability path. C2/C3
and the ablations are deliberately refused by the runner until
`proof/ACTIVE_CONTRACT.md` describes a real automatic Prime event path. A
callable Python API or a manually selected `brainctl` command is not C3 and
cannot satisfy G16/P7.

Inputs under `tasks/`, `fixtures/`, `conditions.json`, and `manifest.json` are
canonical. `results/` and `snapshots/` are derived and ignored. Final holdout
content is not present until the candidate is frozen and the hash is written.

Run deterministic checks from the repository root:

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m pytest proof\deterministic
```

Run the non-holdout Prime smoke stage only after selecting a model and keeping
the same selector/thinking level for both conditions:

```powershell
$env:PYTHONHOME = $null; $env:PYTHONPATH = $null
.venv\Scripts\python.exe -m proof.runner.run_proof `
  --tasks proof/tasks/training/smoke.json --dataset training `
  --repo . --brain-home . `
  --output proof/results/raw/smoke.jsonl `
  --condition C0_OFF --condition C1_OBSERVABILITY `
  --seed 20260814 --launcher C:\Tools\prime-agent\prime-agent.sh `
  --extension brainstem/prime-extension/src/index.ts `
  --model deepseek/deepseek-v4-flash --thinking minimal --offline
```

The smoke stage is a harness/instrumentation check, not product evidence.
