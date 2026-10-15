---
id: n-e87fa498be
kind: note
at: 2026-10-10T04:05:25Z
source: agent
---

ExtraSS verification: dl.acm.org fullHtml and /doi/pdf return 403 (Cloudflare) to WebFetch and curl even with browser UA; author PDF sites.cs.ucsb.edu/~lingqi/publications/paper_siga23extrass.pdf is ~25+MB and downloads at ~0.5 MB/min (use curl in background, pdftotext on a partial copy already yields Tables 2-3). arxiv.org/pdf WebFetch times out at 300s; arxiv.org/html/<id>v1 works. Session WebSearch budget (200 shared) ran out mid-verification.
