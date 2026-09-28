---
id: n-4ea5c3cd02
kind: gotcha
at: 2026-09-28T05:39:04Z
source: agent
tested: "true"
---

Ettin (.bin-only HF repo) trainings hang forever at process exit
transformers 5.17 spawns a non-daemon "Thread-auto_conversion" whenever it loads pytorch_model.bin with no safetensors, and that thread stalls in xet_get. train.py writes all its outputs, then blocks in threading._shutdown (py-spy dump showed this). Fix: env DISABLE_SAFETENSORS_CONVERSION=1 (runner env for now; bake into lab/model.py after the bb-ettin run). py-spy lives at C:/Users/assas/AppData/Roaming/Python/Python314/Scripts/py-spy.exe.
