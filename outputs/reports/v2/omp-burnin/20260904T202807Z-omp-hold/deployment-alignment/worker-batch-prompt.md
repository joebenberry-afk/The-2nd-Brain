Use the task tool to launch exactly 20 independent read-only subagents in one
batch, each targeting a different file below under
`brainstem/prime-extension/src/`. Each subagent must: read only its assigned
file, count its lines, and report back one sentence: the filename and its
line count. Do not have subagents edit anything. After all 20 finish, reply
with one line: "DONE: <n> succeeded, <n> failed" using the actual counts.

Files (one per subagent):
1. ledger-mirror.ts
2. index.ts
3. autoinject.ts
4. sensors.ts
5. config.ts
6. lean-code.ts
7. worker-context-bridge.ts
8. vmem.ts
9. visibility-bridge.ts
10. rtd.ts
11. routing-bridge.ts
12. recall-gate.ts
13. p4-mirror.ts
14. environment-mirror.ts
15. active-state-mirror.ts
16. worker-result-bridge.ts
17. injection-slots.ts
18. context-paging.ts
19. budget-bridge.ts
20. storage.ts
