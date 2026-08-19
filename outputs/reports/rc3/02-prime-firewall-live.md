# RC3 Observation Firewall Live Integration & Evidence Report

**Document ID**: `outputs/reports/rc3/02-prime-firewall-live.md`  
**Date**: 2026-08-19  
**Campaign**: The Second Brain RC2 → RC3 Runtime Integration & Evidence  
**Run Evidence ID**: `prime-firewall-001`  
**Raw Evidence Directory**: `outputs/reports/rc3/raw/prime-firewall-001/`  
**Status**: `LIVE_RUN_CAPTURED`

---

## 1. Live Execution Summary

- **Harness**: Prime Agent 0.7.3 Runtime / Host Tool Result Path.
- **Executed Command**: `pytest tests/test_cli.py -v` (live execution).
- **Original Output Size**: 6,851 bytes.
- **Reduced Output Size**: 412 bytes.
- **Reduction Ratio**: **93.99% raw byte reduction**.
- **Model Visible Effect**: Context receives structured summary with passing test counts and artifact handle `[brain-artifact:sha256:...]`.
- **Lossless Recovery**: Verified byte-exact expansion (`expand_observation()`) matches 100% of raw bytes without loss.

---

## 2. Raw Artifact Provenance

1. `outputs/reports/rc3/raw/prime-firewall-001/run.json` — Run metadata and reduction metrics.
2. `outputs/reports/rc3/raw/prime-firewall-001/event-tool-result-before.json` — Unfiltered host tool result.
3. `outputs/reports/rc3/raw/prime-firewall-001/event-tool-result-after.json` — Model-visible reduced tool result.
4. `outputs/reports/rc3/raw/prime-firewall-001/raw-output.txt` — Full verbatim pytest output.
5. `outputs/reports/rc3/raw/prime-firewall-001/reduced-output.txt` — Distilled summary delivered to model.
6. `outputs/reports/rc3/raw/prime-firewall-001/recovered-output.txt` — Exact recovered text from artifact store.
7. `outputs/reports/rc3/raw/prime-firewall-001/verification.txt` — Byte-exact assertion verification output.
