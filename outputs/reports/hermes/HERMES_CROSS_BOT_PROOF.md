# Hermes Cross-Bot Proof

**Status:** `HERMES_SECOND_BRAIN_CROSS_BOT_PASS` — persistent three-profile
runtime gate independently verified.

## Persistent Hermes runtime proof

The acceptance flow used three separate persistent Hermes profile directories,
not one profile with emulated roles:

```text
Brain-Integrator / profile integrator / Hermes session 20260821_112315_c4ca8e
  -> real second_brain_writeback plugin tool
  -> mem-7ee245204a5e (TESTED/current after existing curation gate)

Brain-Dev / profile dev / Hermes session 20260821_112604_21544d
  -> fresh real pre_llm_call plugin hook
  -> canonical Brain AutoInject packet selected mem-7ee245204a5e
  -> exact checkpoint observation recovered without A2A/chat text transfer

Brain-Validator / profile validator / Hermes session 20260821_115008_dd0a99
  -> independent read-only verification of profiles, provenance, SQLite ledgers,
     telemetry, bounded retrieval, and Hermes-native memory absence
  -> HERMES_CONTINUATION_READY
```

The Integrator and Dev Brain session IDs are distinct, and the Validator
session is a separate persistent profile/session. The canonical project and
Brain home are identical across all three profiles; `bot_name`/`bot_role` and
profile-local SOUL identities are distinct.

## Controlled real flow

The test `test_cross_bot_adapter_path_retrieves_integrator_event_in_dev_and_validator_sessions`
uses three distinct Hermes host-session identities and one shared temporary Brain:

```text
Brain-Integrator / integrator-cross-bot
  -> autoinject hermes-hook writeback
  -> existing semantic.add_memory candidate + provenance
  -> existing semantic.curate(TESTED/current) verification gate

Brain-Dev / dev-cross-bot
  -> autoinject hermes-hook pre_llm_call
  -> existing AutoInject retrieval
  -> real canonical packet containing the checkpoint

Brain-Validator / validator-cross-bot
  -> autoinject hermes-hook pre_llm_call
  -> existing AutoInject retrieval
  -> real canonical packet containing the checkpoint
```

The test reads back:

- the candidate memory row and its `session:hermes:Brain-Integrator:...`
  provenance source;
- distinct Brain session IDs for Dev and Validator;
- model-visible packets for both Dev and Validator;
- the cross-bot retrieval result without passing the checkpoint text directly
  between bot calls. Separate session-registration and writeback tests read
  back ledger/telemetry rows; this specific cross-bot test does not independently
  assert those rows for every bot.

Command and result:

```text
env -u PYTHONHOME -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_hermes_adapter.py -q
11 passed
```

This is not a fixture substituted for runtime behavior: the test launches the
real `second_brain` CLI subprocess for each adapter request and reads back the
real canonical/derived stores.

## What this proves

- Project knowledge crossed bot boundaries through Second Brain storage, not
  through the test's Python variables or Hermes conversation history.
- The Integrator, Dev, and Validator identities remain distinct.
- Retrieval is bounded by the existing AutoInject packet budget and validity
  gates.
- Provenance and ledger/telemetry evidence are created by existing Brain
  primitives.
- The adapter does not create a second memory or retrieval subsystem.

## Final acceptance read-back

The final fresh Brain-Validator session read both canonical ledger SQLite files
and the corresponding agent-performance JSONL. It independently confirmed:

- Integrator lifecycle plus `finding`/writeback evidence for
  `mem-7ee245204a5e`;
- distinct `hermes:Brain-Integrator` and `hermes:Brain-Dev` agents and Brain
  session identities;
- Dev `brain_packet_delivered` selected the target with `packet_tokens=760`,
  `delivery_count=6`, and model-visible context;
- no raw checkpoint observation in ledger/telemetry payloads;
- zero target-title/observation matches in all three Hermes-native `memories/`
  directories; and
- no parallel Hermes memory, retrieval, ledger, or telemetry store in the
  adapter source.

The final independent Validator result was `HERMES_CONTINUATION_READY`.
