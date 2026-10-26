---
id: n-bfc74e104e
kind: gotcha
at: 2026-10-23T10:13:52Z
source: agent
tags:
  - disk
  - windows
---

WOF/LZX compression (compact /c /s /exe:lzx, at BelowNormal) works only on NTFS C:, freed 62.4 GiB on 756 finished run folders (undo: compact /u /s /exe). D: is exFAT: no compression and 1 MiB clusters, so copying compressed or small-file data to D: costs the apparent size or more. Test a sample first and keep going only at a ratio of 1.25 or more.
