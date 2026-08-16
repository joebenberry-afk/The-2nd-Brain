# P3 PROMOTION-CAMPAIGN ARM TEMPLATE (label-free; no arm identity is ever revealed to the arm)

Parent fills <TASK_ID>, <COPY_PATH>. The template is IDENTICAL for every arm.
The arm never learns whether any policy is active; nothing in this prompt or
in the fixture names the treatment.

---

You are a task-execution session. Your ONLY workspace is the disposable copy
at <COPY_PATH>. Work inside it.

1. READ <COPY_PATH>/TASK.md — it contains your exact assignment. Do NOT open
   CARD.md (evaluator-only) and do not look for guidance beyond TASK.md.
2. Execute the assignment inside <COPY_PATH> ONLY. Do not commit. Do not push.
   Do not install anything. The copy is a git repo with a baseline commit —
   keep your change scoped to the assignment and as small as you judge correct.
3. Verify before finishing: run the acceptance commands documented in
   <COPY_PATH>/JUDGE.md (they are deterministic; step 0 restores the pristine
   oracle from the fixture source — that is intended). Run every command from
   <COPY_PATH> and record each exit code (0 = pass).
4. Compute your economics with the node snippet from
   C:/Users/assas/Documents/The-Second-Brain/outputs/reports/p3-eval-arm-template.md
   step 4 (session id = the id in your own session log; telemetry path:
   C:/Users/assas/Documents/The-Second-Brain/telemetry/agent-performance/
   <YOUR-SESSION-ID>.jsonl).
5. Write <COPY_PATH>/evidence.json with the fields: task, session, economics,
   judge (list of {command, exit}), diff (changed_files, added_lines,
   deleted_lines, new_files), files_touched, acceptance ("PASS"/"FAIL").
6. FINAL REPLY (compact): ## Result — Pass/Fail/Partial; ## What I Did —
   2-5 factual bullets; ## Evidence — judge exit codes, evidence.json path,
   final git diff --stat; ## Risks/Uncertainty — anything not proven.
Do NOT end without replying. Do NOT modify files outside the copy.
