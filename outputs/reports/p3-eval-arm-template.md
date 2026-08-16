# P3-E ARM SESSION TEMPLATE (verbatim prompt to each fresh v4-flash child)

Parent fills `<SLUG>`, `<COPY_PATH>`, `<SESSION_ID>`, `<BRAIN_HOME>` and sets
the env gate (`SECOND_BRAIN_LEAN=advisory` for CANDIDATE arms only; unset for
BASELINE). The template is IDENTICAL for both arms (blinded).

---

You are an evaluation arm session for a paired experiment (task <SLUG>).
Your ONLY workspace is the disposable copy at <COPY_PATH>. Work inside it.

1. READ <COPY_PATH>/TASK.md — the `## TASK PROMPT` section is your exact
   assignment. The `## ACCEPTANCE` and `## BASELINE HINT` sections are
   analysis metadata — do NOT read them into your reasoning; ignore them.

2. Execute the assignment inside <COPY_PATH> ONLY:
   - Never touch the fixture source (`tests/fixtures/lean-code-tasks/<SLUG>`).
   - Do not commit. Do not push. Do not install anything.
   - The copy is a git repo with a baseline commit — your footprint is
     measured with `git diff` / `git status`; keep the change minimal and
     scoped to the assignment.

3. Verify before finishing: run the acceptance commands documented in
   <COPY_PATH>/JUDGE.md (they are deterministic; step 0 restores the pristine
   oracle from the fixture source — that is intended). Run every command from
   <COPY_PATH> and record each exit code (0 = pass).

4. Compute your evidence with this exact snippet (run from <COPY_PATH>;
   replace <SESSION_ID> with your session id; it is the stem of your
   telemetry file, e.g. `01a00abc-...`):

   node -e "const fs=require('fs');const cp=require('child_process');const f=process.argv[1];const rows=fs.readFileSync(f,'utf8').split('\n').filter(Boolean).map(l=>{try{return JSON.parse(l)}catch{return null}}).filter(Boolean);const sum=k=>rows.filter(r=>r[k]!=null).reduce((a,r)=>a+r[k],0);const au=rows.filter(r=>r.kind==='assistant_usage');const tc={};rows.filter(r=>r.kind==='tool_call').forEach(r=>tc[r.tool]=(tc[r.tool]||0)+1);const ai=rows.filter(r=>r.kind==='autoinject_shadow_decision');const ts=rows.map(r=>Date.parse(r.ts)).filter(Boolean);const econ={assistant_usage_rows:au.length,input_tokens:sum('input_tokens'),output_tokens:sum('output_tokens'),cache_read_tokens:sum('cache_read_tokens'),cache_write_tokens:sum('cache_write_tokens'),total_tokens:sum('total_tokens'),cost_total:sum('cost_total'),autoinject_packets:ai.length,autoinject_packet_tokens:sum('packet_tokens'),tool_calls:tc,turns:rows.filter(r=>r.kind==='turn_start').length,wall_ms:ts.length?ts[ts.length-1]-ts[0]:null};const num=cp.execSync('git diff --numstat').toString();let added=0,deleted=0;for(const l of num.split('\n')){const m=l.match(/^(\d+)\s+(\d+)/);if(m){added+=+m[1];deleted+=+m[2]}}const changed=cp.execSync('git diff --name-only').toString().trim().split('\n').filter(Boolean);const porc=cp.execSync('git status --porcelain').toString().trim().split('\n').filter(Boolean).map(l=>l.slice(3));const fresh=porc.filter(p=>!changed.includes(p));console.log(JSON.stringify({session:process.argv[2],economics:econ,diff:{changed_files:changed,added_lines:added,deleted_lines:deleted,new_files:fresh}},null,1))" <BRAIN_HOME>/telemetry/agent-performance/<SESSION_ID>.jsonl <SESSION_ID>

   (If the telemetry file does not exist yet, wait a few seconds and retry;
   records are written by the observability extension throughout your run.)

5. Write <COPY_PATH>/evidence.json with this shape (fill judge + acceptance +
   lc_decisions yourself; the snippet output goes into the `economics` and
   `diff` fields):

   {
     "run_id": "<SLUG>-<arm>-<run number>",
     "task": "<SLUG>",
     "arm": "<arm>",
     "session": "<SESSION_ID>",
     "economics": { ...from snippet... },
     "judge": [ { "command": "...", "exit": 0 } ],
     "diff": { ...from snippet... },
     "files_touched": <count of changed+new files>,
     "lc_decisions": [ ...only if material... ],
     "acceptance": "PASS" | "FAIL"
   }

   LC codes (report ONLY when a decision was material, plan §16.3):
   LC_REUSE (reused existing X instead of new Y), LC_NEW_TOOL_JUSTIFIED,
   LC_DEP_REJECTED, LC_DEP_ACCEPTED, LC_PREP_REFACTOR,
   LC_ABSTRACTION_JUSTIFIED, LC_DEFERRED_DEBT (unrelated cleanup noticed and
   deferred), LC_STOP (stopped at acceptance).

6. RETURN CONTRACT (your final reply, compact):

   ## Result — Pass / Fail / Partial
   ## What I Did — 2-5 bullets, factual
   ## Evidence — judge command exit codes, evidence.json path, final
   `git diff --stat` summary
   ## Lean decisions — LC_* codes + one line each, only if material
   ## Risks / Uncertainty — anything not proven

Do NOT end without replying. Do NOT modify files outside <COPY_PATH>.