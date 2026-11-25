---
id: n-f3dcb47eb5
kind: note
at: 2026-11-19T19:06:27Z
source: agent
checked: uncheckable
checked_at: 2026-11-25T19:05:54Z
checked_why: CH340-vs-MKR Zero port autopick and COM9 are hardware/runtime behaviour; no upload_port in Lab 3 platformio.ini, no trace of the event
checked_sha: c0b467aef877
---

ECNG3006 Lab3 upload: 'No device found on COMxx' = pio auto-picked a CH340 (1A86:7523) board instead of MKR Zero. MKR Zero is VID 2341 (804F sketch / 004F bootloader, was COM9). Unplug the CH340 or set upload_port.
