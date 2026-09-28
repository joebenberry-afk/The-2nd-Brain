---
id: n-433cc9af4b
kind: gotcha
at: 2026-09-28T13:14:47Z
source: agent
---

RTX 5070 Ti Laptop hard-powers off under sustained stock-clock GPU training
Absolute Laya docs/UNDERVOLT_LOG.md: 3 hard power-offs at stock (thermal margin fell to ≤0). Safe point: G-Helper 1650 MHz cap +300 MHz offset (-26% J/step, 64 W peak, margin ≥9). 1800/+400 passed a matmul probe but crashed training with CUDA illegal memory access; validate caps with a real training step. Guard: port Laya lab/energy.py (NVML T.Limit margin every 100 ms, pause <8 °C until 14 °C). BasicUpscaler adopts this in PLAN.md "Training and GPU rules".
