---
name: second-brain
description: Query, retrieve context from, inspect status of, or write durable learnings to The Second Brain. Use when you need project decisions, semantic memory, health checks, or durable knowledge recording.
---

# Second Brain Operational Guide

The Second Brain provides persistent, curated memory and requirement tracking across sessions.

## 1. When to Query the Brain Explicitly
- When starting work on an existing project where past architecture decisions, conventions, or constraints apply.
- When searching for past solutions or decisions: `brainctl memory search "<topic>"`
- When checking project status or registered project metadata: `brainctl project status <project_id>`

## 2. Source Truth vs. Remembered Context
- Memory reflects past observations; current code and tests reflect ground truth.
- Always verify remembered facts against current repository files and test runs before making changes.
- If memory contradicts source code, update or supersede the memory (`brainctl memory supersede`).

## 3. Durable Writeback
Write back only durable, verified, high-value project knowledge (never transient scratch files, conversation noise, or credentials):
- Add candidate memory:
  ```powershell
  .venv\Scripts\python -m second_brain memory add "<title>" "<body>" --scope project --project <project_id>
  ```
- Or write back via AutoInject:
  ```powershell
  .venv\Scripts\python -m second_brain autoinject writeback --session <session_id> --project <project_id> --title "<title>" --observation "<obs>"
  ```

## 4. Status and Health Checks
- Health check: `brainctl doctor`
- Overall status: `brainctl status`
- Promotions / skill levels: `brainctl promotions`

## 5. Failure Handling
- If Second Brain commands fail or return non-zero exit codes, fail open and proceed using direct repository source and tests.
- Never construct parallel ad-hoc memory databases when the Brain is unavailable.
