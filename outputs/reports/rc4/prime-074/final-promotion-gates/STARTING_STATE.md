# STARTING_STATE.md

Fresh session, narrow release-completion task per
`prime_074_final_promotion_gates_rlm_eperm_ab.md`. Only the two open
release-critical gates from the prior external review are in scope:

```
BLOCKER A: fresh RLM spawn -> kernel-bootstrap EPERM -> 3/3 failures
BLOCKER B: fresh controlled Prime v0.7.3 <-> v0.7.4 flaky-test A/B -> incomplete
```

Prior conclusion treated as a hypothesis, not trusted blindly:
`PRIME_0_7_4_SECOND_BRAIN_QUALIFIED_NOT_PROMOTED`
(see `outputs/reports/rc4/prime-074/external-review/`).

## User directive for this pass

- Stay isolated until the RLM root cause and environment matrix are proven.
- Do not restart or modify the live daemon yet.
- Only touch the live Prime install after the pre-promotion gate explicitly
  passes.
- If the current session's own kernel is holding the shared kernel-venv
  open, prove that in isolation and determine the minimum safe fix rather
  than working around it.

## Session self-identity (relevant to Blocker A)

This session's own IPython kernel is itself the live install's shared
kernel Python:

```
sys.executable == C:\Users\assas\.prime\agent\kernel-venv\Scripts\python.exe
PRIME_AGENT_CODING_AGENT_DIR = C:\Users\assas\.prime\agent
PRIME_AGENT_LAUNCHER_PATH = C:/Tools/prime-agent/prime-agent.sh
PRIME_AGENT_BUILD_ID = v0.7.3-dirty
```

i.e. this driver session is, right now, a live holder of the exact file
category (`kernel-venv\Scripts\python.exe`) implicated in the reported
EPERM. This was treated as the primary lead for the isolated repro, per
the user's explicit instruction, rather than something to route around.
