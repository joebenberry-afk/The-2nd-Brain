---
id: n-bee7c75b09
kind: fact
at: 2026-10-06T10:44:45Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-AI-Knowledge\memory\qwen-tts-audiobook-project.md
---

Project at `C:\Users\assas\Documents\AI Knowledge\tts-audiobook` (started 2026-06-28).
Goal: clone user's voice with Qwen3-TTS, convert EPUBs (large web-novel series:
Lord of the Mysteries, Reincarnated as a Slime, Reverend Insanity in Calibre
library at `C:\Users\assas\Calibre Library`) into EPUB3 **media-overlay
read-along** books (sentence-synced highlight) playable in Calibre.

Pipeline package `epubtts/`: textprep (spine->sentences, wrap `<span id>`,
strip translator/editor junk) -> synth (Qwen3 voice clone, prompt built once
& reused) -> audio (trim/pause/concat/loudnorm mp3; per-sentence clip
durations ARE the overlay timestamps, no forced aligner) -> package (EPUB3
OPF patch + SMIL) -> run (batch + per-chapter resumable checkpoints in work/).

Non-obvious setup gotchas (all solved):
- Install qwen_tts from GitHub source (`pip install --no-deps -e .`), NOT PyPI:
  PyPI `qwen-tts` pins ancient numba (py<3.10), `qwen3-tts` demands py3.13.
- transformers 4.57.3 `_patch_mistral_regex` calls model_info() over network
  even for non-Mistral -> hangs online / errors offline. FIX: pass a LOCAL dir
  (snapshot_download path) to from_pretrained, not the repo id.
- qwen_tts needs the **SoX binary** on PATH (winget `ChrisBagwell.SoX`).
- Blackwell RTX 5070 Ti Laptop (sm_120) needs torch cu128. venv = uv, py3.12.
- Model: `Qwen/Qwen3-TTS-12Hz-1.7B-Base`. VRAM ~4.7GB at batch 8 (12GB total).
- Throughput: RTF ~0.57 warm/batched. ~20hr compute per 269-chapter volume.
- flash-attn warning is harmless (only whisper encoder, one-time at prompt build);
  main gen uses sdpa.

Verified working: read-along plays in **Thorium Reader** (EDRLab.Thorium), NOT
Calibre viewer or Readest (both live-TTS only, can't play embedded narration).
Thorium = the player. Do not set media:active-class (let Thorium's built-in
highlight render; custom class didn't show).

CRITICAL throughput finding: use `--xvector` (x_vector_only_mode=True) for batch
jobs. ICL mode (default) prepends the full ref-audio codes to EVERY generation —
with an 18s ref that made batches erratic & huge (one hit 371s). x-vector clones
from speaker embedding only: batches 6-71s, stable, scales with sentence length.
ICL fine only with a very short clean ref.

User's voice: ref.wav (18.8s, from ref.ogg) + ref.txt in project root. Pilot in
their voice validated. Full-volume command:
  python -m epubtts.run "<vol.epub>" --ref-audio ref.wav --ref-text (ref.txt) --xvector
See [[user-profile]] if exists.
