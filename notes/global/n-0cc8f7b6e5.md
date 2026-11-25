---
id: n-0cc8f7b6e5
kind: procedure
at: 2026-11-04T17:47:58Z
source: agent
---

DSH Client→Host channel for a plugin UI: Host `ctx.inject(['connection'], c => c.connection.rpc.handle('/my-channel', async (endpoint, payload, signal, peer) => ({ok:true, value}) ))` (cookie-authenticated like /api; returns are passed through verbatim); Client `ctx.get('connection').rpc.call('/my-channel', endpoint, payload)` → {ok, value|error}. Package needs dsh.client.inject ["@deepseek-ai/dsh-client-connection"]. Settings page = slot `settings.section` {id, order, label}. cordis_inspect_query `input` objects are rejected ("input must be an object") in this harness build — only no-input queries work.
