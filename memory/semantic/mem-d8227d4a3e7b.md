---
id: mem-d8227d4a3e7b
title: The WGC Direct3D11CaptureFrame.SystemRelativeTime stamp is later than the applic
scope: project
project: default
status: candidate
grade: VERIFIED
version: 1
created_at: 2026-09-21T10:17:45.485326+00:00
---

The WGC Direct3D11CaptureFrame.SystemRelativeTime stamp is later than the application's dequeue and Present-return on 92-96% of frames and its deltas fit the display vblank grid (165 Hz, 10.0 us mean residual over 380 deltas, 6060.686 us fitted period); the 100ns-to-QPC conversion is an identity at 10 MHz, so the retired |dequeue-wgc|<=2ms budget was ill-posed and G1 stays BLOCKED with the mechanism explained.
