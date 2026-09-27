---
id: n-31ebcbdea2
kind: gotcha
at: 2026-09-27T20:08:03Z
source: agent
tested: "true"
---

Agent-written tests can pass without checking anything: look for assertions inside if-blocks, >= 0 checks, and tests that only restate the implementation

Seen in the V4 build: Haiku-written suites passed while proposals were never persisted, converted notes lost their bodies, and the fix text repeated its headline. Review a subagent's tests against the spec, not against its code.
