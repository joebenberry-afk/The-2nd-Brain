---
id: mem-28454b0abf5e
title: CountUpUseBlast caller evidence and TEL-next probe
scope: domain
project: 
status: candidate
grade: OBSERVED
version: 1
created_at: 2026-08-28T09:17:23.952858+00:00
---

Static evidence for BuildID 24497537 supports only ASSCharacter::CountUpUseBlast(const EKoratBlastSlotType InSlot) at DBSZ Ultimate AI dump/CXXHeaderDump/SS.hpp:20450 and reflected /Script/SS.SSCharacter:CountUpUseBlast. No native caller/RVA/disassembly/caller graph is available; the indexed EXE hit at decimal offset 110107432 is only a string offset, and the SZ-Tool index mapping is stale versus authoritative MAP-36acb77935ba. Runtime Lua cannot obtain caller PC/module base; it now records bounded blast_callback_diagnostic rows with callback sequence/time, raw/reflected slot values, current Blast ID, identity, GetAddress markers, and explicit unknown thread/caller/RVA fields while leaving semantic acceptance and dedupe unchanged. Source-only manifest e2a7cb9d70169dbc770730557baf9453997303476920a750f47edac77134e58a passes; deployment awaits idle match.
