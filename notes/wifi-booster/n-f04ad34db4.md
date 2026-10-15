---
id: n-f04ad34db4
kind: fact
at: 2026-10-15T12:35:16Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-15T12:35:16Z
tested_sha: 7461cd519495
---

Campus network findings 2026-10-15: (1) Cloudflare WARP can't connect on STA-Students: warp-cli 2026.8 cycles happy-eyeballs to 162.159.198.2 ports 8095/443/1701/4443/500/8443/4500 for 90 s with both WireGuard and MASQUE; DNS breaks while it is "Connecting". Installed then uninstalled (msiexec /x, exit 0). (2) Don't switch DNS to 1.1.1.1: worse CDN mapping (dl.google.com 128 vs 77 ms, huggingface.co 131 vs 72, download.pytorch.org 89 vs 72) vs DHCP 8.8.8.8. (3) Single-flow QUIC beats TCP only to Google (dl.google.com 11-15 vs 1-1.3 Mbps); Fastly/jsDelivr QUIC ~0.5 Mbps. (4) Local Cloudflare POP (POS, ~25-28 ms) is fast per flow (nodejs.org 7-13 Mbps); international CDNs (~72 ms Miami) 0.1-1 Mbps/flow at night. torch wheels now on download-r2.pytorch.org (Cloudflare R2): 64 conn ~50 Mbps at 03:00. (5) hf_xet 1.6 adaptive concurrency already parallel; HF_XET_FIXED_DOWNLOAD_CONCURRENCY=64/HIGH_PERFORMANCE showed no consistent gain (noisy). (6) Wi-Fi: Roaming Aggressiveness 2. Lowest + Preferred Band 5 GHz applied via %LOCALAPPDATA%\aria2-rpc\wifi-tune.ps1 (-Undo restores). (7) aria2 writes at spread offsets: partial test files of a 2.5 GB wheel occupy GBs on NTFS even when stopped early; delete test dirs.
