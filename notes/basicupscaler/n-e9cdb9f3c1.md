---
id: n-e9cdb9f3c1
kind: decision
at: 2026-10-17T05:59:59Z
source: agent
---

JPEG XL is NOT used for BUFG data (decided 17 Oct 01:44Z, owner leaned option A; never implemented)
Owner installed the Windows JPEG XL Image Extension (a viewer/WIC codec only) and asked about saving space. Lossless JXL (distance 0) is pixel-exact (−28.6 % on one tested frame) but not byte-exact. M1/M2 freezes and receipts bind PNG SHA-256 values and .png names, and tools/cv2/Rust readers expect .png. A loose .jxl on D: (exFAT, 1 MiB clusters) saves nothing for files ≤1 MiB.
Actual space method: verified ZIP moves to D:\BU-gen\runs-archive with a per-file SHA-256 manifest (FG-303). Deflate shrinks JSON about 45× but PNG 0 %.
The "option A" deletion path from that discussion is what removed 17,939 protected PNGs (FG-321, recovered FG-322).
Only consider JXL for cold, unreferenced frames inside archives, as a tested tooling change.
