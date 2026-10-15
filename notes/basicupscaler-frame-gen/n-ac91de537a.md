---
id: n-ac91de537a
kind: gotcha
at: 2026-10-13T04:46:02Z
source: agent
tested: "true"
tested_by: agent
tested_at: 2026-10-13T04:46:02Z
tested_sha: f24773f7831f
---

Never name a script in a receipt folder after a stdlib module (queue.py, json.py, test.py...): running any other script from that folder puts it on sys.path[0], and `import queue` (pulled in by threading/concurrent/subprocess users) executes the shadowing script. On 13 Oct an FG-235 queue.py got executed by an agent's unit test and started `tools.bench wait` + a pending `arena.fg235 execute`. Use prefixed names (fg235_queue.py).
