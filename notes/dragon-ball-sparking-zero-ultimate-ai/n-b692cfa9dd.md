---
id: n-b692cfa9dd
kind: decision
at: 2026-10-06T10:45:02Z
source: claude-memory
evidence:
  - claude-memory:C:\Users\assas\.claude\projects\C--Users-assas-Documents-Dragon-Ball-Sparking-Zero-Ultimate-AI\memory\check-existing-video-evidence-first.md
---

Before asking Joseph to run an in-game test for the AIplus project, check
`Videos/` in the repo — he records full test blocks there (`N0 Test`, `A4 Test`,
`Smoke Test`, `General test`, `Combat Guides`) and expects them to be read.

**Why:** on 2026-08-10 I proposed "run N0 Arm A next" as the priority gate when
`Videos/N0 Test/N0 Test 1-10.mp4` already contained the complete 10-match block.
He replied "we have video already check them out". Reading it resolved the open
question and also exposed a mislabeled arm in the repo's own results CSV.

**How to apply:** `ffmpeg` and `PIL` are available. The working method is to
extract the top-left HUD fighter portrait as a raw colour stream
(`fps=2,crop=190:170:25:80,scale=48:43,format=rgb24`), greedy-cluster the
frames, then identify each cluster visually from representative crops — a form
change swaps a fixed UI sprite, so it clusters cleanly. Grayscale is not enough:
it merges Frieza's 1st and 2nd Form portraits. Always validate the classifier
against one of his manual tallies before trusting it on unlabeled footage. Menu
screens at the start of each recording carry the CPU Settings selector, stage,
difficulty, and rule settings — read them to pin the arm. Related:
[[aiplus-performance-constraint]].
