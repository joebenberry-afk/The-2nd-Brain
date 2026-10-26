---
id: n-5fe47b9b2a
kind: note
at: 2026-10-24T16:42:15Z
source: agent
---

ETW real-time gotcha (BU timebase, 24 Oct): a session's BuffersWritten (ControlTrace QUERY/FLUSH output) counts buffers the real-time consumer never receives, and after the third flush also that flush's own buffer, which only a later flush delivers. Own-process 300 s run: deficit settled at 7 while ProcessTrace's BuffersRead equalled our BufferCallback count and no event was lost. So a consumer-side buffer count can never be a wait reference; request_flush now waits for its own sentinel event (per-instance provider GUID, written after the first of three flushes).
