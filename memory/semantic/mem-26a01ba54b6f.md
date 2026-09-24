---
id: mem-26a01ba54b6f
title: T1 Control 1 caller-cluster result
scope: domain
project: 
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-28T09:33:23.478184+00:00
---

After Control 1 baseline sequence 1163, one user-reported P1 Kefla Blast Skill 1 activation on diagnostic bundle e2a7cb9d70169dbc770730557baf9453997303476920a750f47edac77134e58a produced 8 blast_callback_diagnostic rows and 3 accepted blast_used events. Health: 8 callbacks, 3 accepted, 1 duplicate-window rejection, 4 invalid-context rejections, 0 missing-identity/invalid-slot rejects, 0 callback errors, 0 queue drops, 0 sequence gaps. Object cluster address:2161795574448 had 6 callbacks (four with P1 Kefla form 0920_00 identity after context readiness); address:2161782292496 had 2 pre-context callbacks with no identity. Raw slot args were garbage 88,88,19,144,142,88 and 88,88; reflected combo slot remained 3/BlastSkill1; current Blast ID was 0/1. Thread/caller/RVA stayed unknown because UE4SS Lua exposes no caller-PC API. No 1:1 caller cluster; stop further activation trials and do not change dedupe.
