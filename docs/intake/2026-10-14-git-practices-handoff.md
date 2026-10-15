# Git / GitHub practice for agents — research handoff

Date: 2026-10-14. Status: **recommendation, not yet implemented.** Owner asked for this to be
handed to the agent working on The Second Brain.

Binding context: `AGENTS.md` (repo rules 1–5) and plan v4 §3.2 still win on conflict. Branch
`brain/<feature>`; commit categories `brain(core|memory|project|adapter|policy)`; full gate
`npx eslint src test && npx tsc --noEmit && npx vitest run` after any change in `brain/`.

## 1. Conclusion

The default with the best evidence is **GitHub flow / short-lived-branch trunk-based
development**, made stricter for agents:

- one task per short-lived branch;
- one logical change per PR;
- a commit at every passing checkpoint;
- squash-merge to a protected `main`;
- a written handoff at the end of each session.

Instruction files only advise; they don't enforce. Enforcement has to come from hooks,
permission rules, CI and server-side branch rules. Sources are in §6.

Evidence strength:
- **Well-supported:**
  - git-flow's author recommends GitHub flow for continuous delivery [S01].
  - DORA defines trunk-based development as small batches merged at least daily [S02].
  - DORA warns against massive AI-generated PRs [S03] and calls frequent commits a
    "critical safeguard" with AI [S04].
  - GitHub's merge, ruleset and Actions-security mechanics [S06–S08, S17–S20].
- **Conditional:**
  - Agent-PR studies: open-source repos only; merge rate is a weak quality proxy [S32–S35].
  - DORA 2023 found only a *minor* delivery gain from trunk-based development, and more
    burnout [S05].
- **Unproven:** no study shows that prose git rules in an agent instruction file reduce
  risky git commands [S37]. That is why §4 asks for enforcement.

## 2. Measured state of this repo (2026-10-14)

| Check | Result | Consequence |
|---|---|---|
| Visibility / plan | PRIVATE; `gh api .../rulesets` and `.../branches/main/protection` return **HTTP 403 "Upgrade to GitHub Pro or make this repository public"** | Nothing server-side stops a direct push or force-push to `main`. Repo-level secret scanning is likely unavailable too [S21]. |
| Merge methods | merge, squash, rebase all allowed; `deleteBranchOnMerge: false` | Free to fix (T5). |
| Local branches | 34, of which 17 are already merged into `main` (`git branch --merged main`) | Prune (T4). |
| Commit granularity | e.g. `27b2146` bundles ~8 changes in one commit | Breaks the one-logical-change rule; coarse revert and bisect. |
| CI (`.github/workflows/ci.yml`) | `permissions:` set (good); `actions/checkout@v4`, `actions/setup-node@v4`, `oven-sh/setup-bun@v2` on floating tags | Supply-chain hardening (T6, optional). |
| `.gitattributes` | `text=auto` + per-path `eol` | Already correct; no change. |

## 3. The philosophy (the text agents should receive)

### 3a. Full version (for a rule file / docs)

```markdown
## Git: how to start, work, and leave a project

Start (look before you change anything)
- Run `git status`, `git branch --show-current`, `git log --oneline -10`, `git fetch`,
  then compare with origin/main. Read AGENTS.md and the progress/handoff note.
- Changes you did not make in the working tree belong to the owner. Never stash, reset
  or check out over them.
- Run the project's test gate once before editing, so you have a known baseline.

Branch
- Never commit to main. One task = one fresh branch from an up-to-date origin/main
  (`<area>/<task>`), or a git worktree when agents run in parallel.
- A branch lives hours to a few days. Then it is merged or deleted.
- One logical change per branch/PR. If the summary needs "and", split it.

Commit
- Commit at every passing checkpoint, so a bad turn costs one `git revert`, not a session.
- Subject in the imperative, about 50 characters (72 at most), using the repo's prefix
  convention. The body says why and how it was checked.
- Stage named paths and read `git diff --cached` before committing. Never commit
  secrets, `.env`, or generated/derived state.
- Never edit or delete a test to make it pass. Report the wrong test separately.

Integrate
- Push the branch and open a PR. Keep it a draft until the gate passes.
- The PR body states what, why, the verification evidence, the risks, and `Closes #N`.
- Squash-merge once CI is green, then delete the branch. main stays linear and every
  PR can be reverted as one unit.
- Releases: annotated tag `vX.Y.Z` (SemVer if there is a public API) plus a changelog
  entry. A published tag never moves.

Never do these unless the owner says so in this conversation
- Force-push to a shared branch. On your own branch use
  `--force-with-lease=<branch>:<expected-sha>` only.
- `reset --hard`, `clean -fdx`, `checkout -- .`, `stash drop`, `branch -D`, history
  rewrites, `--no-verify`, a `skip-checks: true` trailer, or a `Signed-off-by` written
  for a human.

Leave (hand off)
- Commit (or deliberately park WIP on the branch) and push.
- Confirm with `git log` that the commit exists.
- Update the handoff note: goal, done, next, blockers.
- Leave `git status` clean, or explain why it isn't.
```

### 3b. Compact version (for the managed AGENTS.md block, every token counts)

```text
Git: start with `git status`, `git log --oneline -10`, `git fetch`; changes you did not make belong to the owner, never reset/stash/checkout over them.
Never commit to main: one task = one fresh short-lived branch (or worktree) from origin/main, one logical change, squash-merge after CI, delete the branch.
Commit at every passing checkpoint; stage named paths, read `git diff --cached`; never commit secrets or derived state; never weaken a test to pass.
Without the owner's say-so: no force-push to shared branches, reset --hard, clean -fdx, branch -D, history rewrite, --no-verify. End: commit, push, confirm in git log, update the handoff note.
```

## 4. Tasks (owner recommendation: T1 + T2–T4 + T5; T6 optional)

**T1 — Ship the rules to every agent through the Brain** (`brain(adapter)`)
- Where: `AGENTS_BLOCK` in `brain/src/cli.ts:61`, emitted by `brain hook agents-md`
  (`cli.ts:785-789`).
- Change: append the §3b compact text to the block. Do not paste §3a; it would add tokens to
  every session in every project. Plan v5 budgets the card, so measure the token cost first.
- Put §3a at `docs/git-practice.md`, or skip it if §3b is enough. Don't create both a doc and
  a duplicate rule file.
- Acceptance:
  - `brain hook agents-md` prints the new lines.
  - Existing tests that check the block are updated without pinning its wording (repo test
    policy).
  - Full gate is green; frozen recall eval still dev ≥ 13/15, held-out ≥ 7/8.
  - Block token cost before/after is reported.
- Check: does re-running the installer replace the old block in already-installed projects,
  or does it only add a block when none exists? Verify on a scratch clone.

**T2 — Local `pre-push` hook: refuse pushes to `main`** (`brain(policy)`)
- Why: with no server-side protection (403 above), this hook is the only thing stopping a
  push to `main`.
- Shape:
  - committed hook script (e.g. `.githooks/pre-push`), enabled with
    `git config core.hooksPath .githooks`;
  - rejects any refspec whose remote ref is `refs/heads/main` and any deletion of `main`;
  - escape hatch is the owner's explicit `git push --no-verify`, never an agent's.
- Must run under Git Bash on Windows (`*.sh text eol=lf` is already in `.gitattributes`;
  extensionless hook files need an eol rule too).
- Acceptance:
  - In a scratch clone with a bare remote, `git push origin HEAD:main` fails with a clear
    message.
  - `git push origin brain/x` succeeds.

**T3 — Secret scanning before commit** (`brain(policy)`)
- Why: of confirmed leaked secrets in agent PRs, humans committed 67.6% and review missed
  81% [S32]. Repo-level GitHub secret scanning is likely unavailable on this private Free
  repo [S21].
- Options:
  - gitleaks pre-commit hook. External binary: `AGENTS.md` rule 4 governs only `brain/src`,
    but get the owner's OK before adding the tool dependency.
  - Or a gitleaks step in CI (`.github/workflows/ci.yml`).
- Acceptance: a commit staging a fake AWS-style key is rejected; a clean commit passes.

**T4 — Prune merged branches** (no commit)
- `git branch --merged main` listed 17 on 2026-10-14. Delete only those with `git branch -d`
  (the lowercase form refuses unmerged branches).
- Never `-D`. List the result for the owner.
- Leave remote branches alone unless the owner asks.

**T5 — GitHub repo settings** (owner or agent with `gh`; free plan)
- `gh repo edit joebenberry-afk/The-2nd-Brain --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false --delete-branch-on-merge`
- Acceptance: `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed,deleteBranchOnMerge`
  shows true/false/false/true.

**T6 (optional) — Actions supply chain**
- Pin the three actions to full commit SHAs, or adopt the workflow dependency lockfile.
  The lockfile is GitHub's top recommendation but still in **public preview** [S17, S18].
- Add `.github/dependabot.yml` with the `github-actions` ecosystem.

## 5. Owner decisions (not for the agent to make)

- **Server-side protection:** GitHub Pro, or make the repo public. Either one unlocks
  rulesets.
- Solo-owner ruleset if unlocked:
  - require PR with **0 approvals** (N approvals deadlocks a single reviewer);
  - required status check = the CI job;
  - block force-push and deletion;
  - turn on "do not allow bypassing", because agents run with the owner's credentials
    [S07, S08].
- Whether to adopt Conventional Commits. Current `brain(<category>):` prefixes already serve
  the purpose; there is no evidence that switching improves outcomes.
- The repo's existing habit of bundled commits (e.g. `27b2146`). Changing it means more,
  smaller commits and PRs.

## 6. Sources (accessed 2026-10-14; ✓ = re-opened by the lead researcher)

| ID | Source | Venue · date |
|---|---|---|
| S01 ✓ | [A successful Git branching model – 2020 note](https://nvie.com/posts/a-successful-git-branching-model/) | nvie.com · 2010/2020 |
| S02 ✓ | [DORA: Trunk-based development](https://dora.dev/capabilities/trunk-based-development/) | dora.dev |
| S03 ✓ | [DORA: Working in small batches](https://dora.dev/capabilities/working-in-small-batches/) | dora.dev · 2025-12-08 |
| S04 ✓ | [DORA: Version control](https://dora.dev/capabilities/version-control/) | dora.dev · 2026-01-12 |
| S05 | [DORA 2023 report](https://cdn.prod.website-files.com/6542f47b9de43e13b9e4ca9b/65d6b7b5af571001e896b5c3_2023_final_report_sodr_compressed.pdf) | Google Cloud · 2023 (survey) |
| S06 | [About pull request merges](https://docs.github.com/en/pull-requests/reference/pull-request-merges) | GitHub Docs |
| S07 | [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) | GitHub Docs |
| S08 | [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) | GitHub Docs |
| S14 ✓ | [git-push (`--force-with-lease`)](https://git-scm.com/docs/git-push) | git-scm |
| S17 ✓ | [Secure use of GitHub Actions](https://docs.github.com/en/actions/reference/security/secure-use) | GitHub Docs |
| S18 ✓ | [Workflow dependency lockfiles](https://docs.github.com/en/actions/concepts/security/workflow-dependency-lockfiles) | GitHub Docs · public preview |
| S19 ✓ | [Safer pull_request_target defaults](https://github.blog/changelog/2026-06-18-safer-pull_request_target-defaults-for-github-actions-checkout/) | GitHub changelog · 2026-06-18 |
| S20 | [GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token) | GitHub Docs |
| S21 | [Secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning) | GitHub Docs |
| S23 ✓ | [Linux kernel: AI coding assistants](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/process/coding-assistants.rst) | kernel docs |
| S24 ✓ | [AGENTS.md](https://agents.md/) | AAIF / Linux Foundation |
| S27 | [Claude Code permissions (deny rules are not a boundary)](https://code.claude.com/docs/en/permissions.md) | Anthropic docs |
| S31 ✓ | [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | Anthropic Engineering · 2025 |
| S32 ✓ | [Security smells in agent PRs (arXiv 2607.12428)](https://arxiv.org/abs/2607.12428) | arXiv preprint · 2026 |
| S33 | [Agent vs human PR structure (arXiv 2601.17581)](https://arxiv.org/abs/2601.17581) | MSR '26 |
| S34 | [Agent PR merge rates (arXiv 2602.08915)](https://arxiv.org/html/2602.08915v2) | arXiv preprint |
| S35 | [Why agent PRs are rejected (arXiv 2605.22534)](https://arxiv.org/abs/2605.22534) | arXiv preprint |
| S37 | [Agent context files study (arXiv 2511.12884)](https://arxiv.org/abs/2511.12884) | arXiv preprint · 2025 |
