---
id: n-0fd1e4e91d
kind: note
at: 2026-10-24T13:06:57Z
source: agent
---

BUFC 24 Oct: rerun 6 predecessor keys (0.7-1.7% at 60/82.5/60h) = flush race: request_flush returned after 3 ControlTrace FLUSH before the consumer stored the Present. Fix 19bf3b39: BufferCallback counts finished buffers; request_flush spins (lock poll, max 1 ms) until count >= BuffersWritten. Settled counts match (1/1, 219/219, 447/447, 870/870; after 299,485 lost events too). Own-process 21 -> 100/100 stored by return. NOT live-confirmed. Long flush calls reproduce with no game/capture (12.4-14.6 ms max per 600-800 calls, before and after the wait); cause open. README 8905cb51.
