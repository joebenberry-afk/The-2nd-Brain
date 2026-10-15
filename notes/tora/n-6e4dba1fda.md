---
id: n-6e4dba1fda
kind: decision
at: 2026-10-07T22:17:11Z
source: agent
evidence:
  - results/REPORT.md
  - IDEAS.md
evidence_sha:
  - results/REPORT.md=c06c26057446
  - IDEAS.md=5fc3b414ce3d
tested: "true"
tested_by: agent
tested_at: 2026-10-07T22:17:11Z
tested_sha: eb4f7cbc8680
---

Tora bench verdict (7 Oct 2026): EmbeddingGemma 2 is a good System-1 base on this laptop as a CPU llama.cpp service — b11476 llama-server, ggml-org text Q8_0 GGUF, 4 threads on the far CCD, notes chunked to 512 tokens, --cache-ram 0: 858 MB WS / 750 MB private, 0 VRAM, recall 16 ms, frozen recall 14/15 + 7/8 (BM25 13/15, 7/8), real held-out 2 right/0 wrong (= BM25+Jev), Jev AUC 0.96. Failed: torch.ao int8, static Model2Vec-style distill, Jev-probability calibration from cosine. Python processes: OPENBLAS_NUM_THREADS=1 (numpy 759→115 MB) and bounded ONEDNN_PRIMITIVE_CACHE_CAPACITY (−900 MB); torch CUDA import alone costs ~880 MB private. Details: Tora/IDEAS.md, results/REPORT.md.
