---
name: create-github-gate-issues
description: Conversationally publish GitHub tracking issues for a task's lifecycle gates, and linked approval issues assigned to each gate's authority, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "create GitHub issues for this task's gates," "track approvals in GitHub," "publish gate issues," or "make GitHub issues for the approvers" for a project already onboarded with lifecycle-onboarding-github. This is the opposite direction from lifecycle-review-github: it writes new issues to GitHub, it does not read an existing approval back into the kernel.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# GitHub gate tracking

Use this skill to drive `agentic-sdlc create-github-gate-issues` end to end
through a plain-language conversation. It creates one GitHub issue per
applicable lifecycle gate, plus one linked "approval" issue per gate per
required authority role, **assigned to that authority's real GitHub
account**. This is a deliberate, narrowly-scoped exception to this suite's
usual data-minimization posture — the human you are talking to should
understand that before anything is created, not discover it afterward.

This is unrelated to `lifecycle-review-github`: that skill reads an
*already-existing* GitHub PR review back into the kernel as a gate decision.
This skill only creates tracking issues; **closing or commenting on one of
these issues is never itself an approval** — the kernel never reads them
back. Approval still only happens via `agentic-sdlc decide` or
`approve-from-github`/`approve-from-github-pr` (see `lifecycle-review-generic-github`/
`lifecycle-review-github`).

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-github` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`create-github-gate-issues`/`list-github-gate-issues` (run
`./bin/cadre sdlc --help`). If missing, tell the human a kernel upgrade is
needed and stop.

Reuse the GitHub repository (`owner/name`) and the bot/service account login
(`--as-bot`) too if already established earlier in this conversation.
Otherwise ask for them. Never guess either value.

**Ask about the repository's visibility before running anything.** GitHub
issues have no per-issue "confidential" flag the way GitLab does. Gate and
approval issues carry gate names, phases, sanitized rationale, and authority
role labels — on a public repository, that means these details would be
published for anyone to see. If the human confirms the repository is public
and they still want to proceed, the command requires `--allow-public-repo`
to be passed explicitly; do not pass it without the human having said so.
If the repository is private, no extra flag is needed. If they are not sure
of the repository's visibility, help them check before proceeding — do not
guess or default to either answer.

## Step 1 — Check what already exists

Run:

```sh
./bin/cadre sdlc list-github-gate-issues --root <path> --task-id <task-id>
```

Summarize existing tracking issues in plain language (which gates already
have an issue, which authorities already have an assigned approval issue).
This tells the human what re-running will reuse versus newly create.

## Step 2 — Scope

Ask which gates this run should cover — all eligible gates (the default), or
a specific subset (`--gates G3,G9`). Default to all eligible gates if they
don't have a preference. Do not invent a subset.

## Step 3 — Always dry-run first

Run without `--apply` (the kernel's own default):

```sh
./bin/cadre sdlc create-github-gate-issues --root <path> --task-id <task-id> \
  --repo <owner/name> --as-bot <bot-login> --allow-classification <classification> \
  [--gates <G_id,...>] [--allow-public-repo]
```

`--allow-classification` must exactly match the task's recorded
classification — ask the human if you don't already know it from the run
record; never guess it. Only include `--allow-public-repo` here if the human
already confirmed the repository is public and accepted that in the
"Before you start" step.

Parse the JSON yourself. Summarize in plain language, per gate: which gate
issues would be created vs. reused, and for each approval issue, **who it
would be assigned to** (the resolved GitHub login) — this is the moment the
human needs to actually see and confirm real names/usernames before anything
is posted to GitHub, not skip past. Also surface plainly:

- Any `refusals` (an authority couldn't be resolved to a GitHub account, or a
  self-approval conflict was detected) — explain each in plain terms using
  the reason-code table in Step 5, and that those specific issues will not be
  created even on `--apply`.
- Any `skipped` entries (a gate/authority genuinely doesn't apply) — these are
  expected and not a problem.

**Never proceed to Step 4 without the human explicitly confirming the
assignments shown in this dry-run.** Creating an issue and assigning a real
person is a consequential, externally-visible action — treat this the same
way this suite treats any other mutation requiring human confirmation.

## Step 4 — Apply, only after explicit confirmation

Take the `--plan-digest` value from the dry-run's output and run:

```sh
./bin/cadre sdlc create-github-gate-issues --root <path> --task-id <task-id> \
  --repo <owner/name> --as-bot <bot-login> --allow-classification <classification> \
  [--gates <G_id,...>] [--allow-public-repo] --apply --plan-digest <digest>
```

If the kernel reports the digest is stale (something changed between dry-run
and apply — an authority's GitHub binding, a rationale, gate status), do not
retry with a stale value or guess around it: re-run Step 3's dry-run, show
the human what changed, and get fresh confirmation before applying again.
The same rule applies if any other input changes between dry-run and
apply (gates in scope, repository, classification) — a stale digest always
means back to a fresh dry-run and a fresh confirmation, never a retry with
the old digest.

Parse the result. Report plainly: which issues were created, which were
reused (already existed), which were refused (and why, per gate/authority),
and any assignee drift detected on a reused issue (see Step 6).

## Step 5 — Translate refusal reason codes

Never show raw reason codes; translate them:

- `authority-unknown` — that role has no entry in `.agentic-sdlc/authorities.json`
  yet; point back at `lifecycle-onboarding-github`'s Step 4.
- `authority-unassigned` — the role exists but has no one assigned; same
  pointer.
- `no-github-binding` — the assigned person's identity isn't in GitHub-login
  form (e.g. it's a bare email or a GitLab identity); they need a
  `github_login` set for that authority in `authorities.json`.
- `github-user-unresolved` — that login does not resolve to an existing
  GitHub user; check for a typo. (Unlike GitLab, GitHub's user lookup is
  exact-match, so there is no separate "ambiguous match" code to translate.)
- `not-a-collaborator` — the login resolves to a real GitHub user, but they
  are not a collaborator on this repository, so GitHub cannot be trusted to
  actually apply the assignment; they need collaborator access first.
- `applicability-unknown` — the run record can't yet tell whether this
  authority applies to this gate; resolve the authority assignment first.
- `self-approval` — the resolved person is a preparer or independent verifier
  for this gate; a different, independent person needs to be assigned that
  role before an approval issue can be created for them.

A non-empty refusal list does not mean the whole run failed — report exactly
which specific gates/authorities succeeded, were skipped, and were refused,
never collapse this into a single pass/fail statement.

## Step 6 — Assignee drift on re-runs

If a reused approval issue's current GitHub assignee no longer matches the
authority's current resolved login (someone edited `authorities.json`, or
someone manually reassigned the issue in GitHub), the kernel reports this as
drift rather than silently changing anything. Tell the human plainly what
changed and ask whether they want it corrected — only re-run with
`--reconcile-assignees` if they explicitly say yes; never pass that flag
proactively.

Also mention, if it comes up: GitHub can silently drop an assignment to a
non-collaborator rather than reject it outright, so this command double-checks
after every create and every `--reconcile-assignees` update; if that
re-check ever finds the assignment did not actually take, the run blocks
rather than reporting a false success. That is not something you need to
explain unprompted, but do not describe an assignment as final without it
having passed this verification.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never run `--apply` without the human having explicitly seen and confirmed
  the dry-run's assignments first — this is the one hard rule of this skill.
- Never fabricate a repository name, bot login, gate list, or plan digest.
- Never pass `--allow-public-repo` without the human having explicitly
  confirmed the repository is public and accepted that gate/approval details
  will be visible there.
- A created or closed GitHub issue is never itself approval evidence — always
  correct a human who implies otherwise, and point them at `lifecycle-review-generic-github`/
  `lifecycle-review-github` for actually recording a decision.
- Summarize outcomes in prose after each step.
