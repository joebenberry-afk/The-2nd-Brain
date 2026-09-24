# docs/intake — the drop folder

Drop new plans, research, requirements, prompts, reports and decisions here. One folder, any type.
Nothing in this folder is authority. A file here is a proposal, a note or a record; it grants no
permission and authorises no work. A plan is not an instruction. Only a file that has been promoted
into `docs/requirements/` states a current requirement, and promotion happens only by the rule below.

## Naming

    YYYY-MM-DD-<type>-<slug>.<ext>

`<type>` is one of `plan`, `requirement`, `research`, `prompt`, `decision`, `report`. The date is the
date the document speaks for, not the date you wrote it. Lowercase hyphenated slug, at most six
words. Example: `2026-09-22-requirement-v3-no-op-neutrality.md`.

## Front matter

Start every file with this block. It is what makes the file self-classifying: promotion reads only
this block, never the prose.

```yaml
---
date: 2026-09-22
type: requirement
authority: proposed
status: draft
scope: v3-request-neutrality
supersedes: none
superseded-by: none
promoted:
---
```

| Field | Values | Meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | The date this document speaks for. |
| `type` | `plan` / `requirement` / `research` / `prompt` / `decision` / `report` | What kind of document this is; decides the archive subfolder if it supersedes something. |
| `authority` | `proposed` / `current` / `evidence` / `superseded` | Whether this file grants anything. Only `current` does. |
| `status` | free text | Draft, in-review, accepted, rejected. Informational. |
| `scope` | one short token | The requirement area this file governs. |
| `supersedes` | filename in `docs/requirements/`, or `none`, or `none-additive` | What this file replaces. |
| `superseded-by` | filename | Written by the promotion log. Leave `none`. |
| `promoted` | `YYYY-MM-DD` | Set only during promotion. Empty means not promoted. |

## How a dropped file becomes part of the current requirements

Promotion happens only when all four gates hold:

1. `authority: current`.
2. `promoted:` contains an ISO date.
3. `scope:` is present and no file currently in `docs/requirements/` has `authority: current` with
   the same scope.
4. `supersedes:` is `none-additive`, or names a file that exists in `docs/requirements/`.

`none` means "I did not think about it" and BLOCKS promotion. `none-additive` means "this adds to the
current set without replacing anything" and permits it.

The mover then does exactly this, in this order:

1. `git mv docs/intake/<file> docs/requirements/<file>` — filename unchanged, no renames.
2. For each name in `supersedes:`: `git mv docs/requirements/<name>` to
   `docs/archive/superseded-plans/` when `<type>` is `plan` or `requirement`, and to
   `docs/archive/superseded-prompts/` when `<type>` is `prompt`. Do not edit the moved file.
3. Append one line to the supersession log in `docs/requirements/README.md`:
   `<moved file> superseded by <promoted file>, <promoted date>`.
4. Add one row to the current-authority table in `docs/requirements/README.md`.

If any gate fails the file stays in `docs/intake/` and is read as reference. Record the refusal in
one line of the intake log in `docs/requirements/README.md` so it is not re-litigated.

## Worked example

You drop `docs/intake/2026-09-22-requirement-v3-no-op-neutrality.md` with `authority: proposed`. It
changes nothing. Later you edit ONLY the front matter to `authority: current`, `promoted: 2026-09-25`,
`supersedes: Second_Brain_V3_Roadmap_2026-09-21.md`. The mover moves it into `docs/requirements/`,
moves the named roadmap into `docs/archive/superseded-plans/`, logs the supersession, and adds the
row. The archived roadmap is untouched and still readable.

## Two stop conditions — ask the owner, do not decide

1. `supersedes:` names a document that is NOT inside `docs/requirements/` (for example the v2
   register, which lives in `docs/superpowers/plans/`, or the v4.2 plan in the days when it still sat
   at the repository root). That means the authority set itself is being re-cut: the owner decides,
   and pointer edits happen before the move.
2. Two files in `docs/intake/` both declare `authority: current` with the same `scope`. Resolve in the
   owner's session. Never promote both, never merge two proposals' text.

## Never

- Never delete a file. Superseded material moves to `docs/archive/`.
- Never edit a file after it has been archived. The supersession lives in the log, not the old text.
- Never promote a file whose `authority` is `proposed`, `evidence` or `superseded`.
- Never move a file from `docs/archive/` back into `requirements/`; issue a new dated document instead.
- Never treat a file in this folder as authoritative because it is new, detailed, or written by an agent.
