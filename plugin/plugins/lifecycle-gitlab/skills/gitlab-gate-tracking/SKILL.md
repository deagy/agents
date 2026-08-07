---
name: gitlab-gate-tracking
description: Conversationally publish GitLab tracking issues for a task's lifecycle gates, and linked approval-subtask issues assigned to each gate's authority, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "create GitLab issues for this task's gates," "track approvals in GitLab," "publish gate issues," or "make GitLab subtasks for the approvers" for a project already onboarded with lifecycle-onboarding-gitlab. This is the opposite direction from lifecycle-review-gitlab: it writes new issues to GitLab, it does not read an existing approval back into the kernel.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# GitLab gate tracking

Use this skill to drive `agentic-sdlc create-gate-issues` end to end through a
plain-language conversation. It creates one GitLab issue per applicable
lifecycle gate, plus one linked "approval" issue per gate per required
authority role, **assigned to that authority's real GitLab account**. This is
a deliberate, narrowly-scoped exception to this suite's usual
data-minimization posture — the human you are talking to should understand
that before anything is created, not discover it afterward.

This is unrelated to `lifecycle-review-gitlab`: that skill reads an
*already-existing* GitLab MR approval back into the kernel as a gate
decision. This skill only creates tracking issues; **closing or commenting on
one of these issues is never itself an approval** — the kernel never reads
them back. Approval still only happens via `agentic-sdlc decide` or
`approve-from-gitlab`/`approve-from-gitlab-mr` (see `lifecycle-review-generic-gitlab`/
`lifecycle-review-gitlab`).

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-gitlab` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`create-gate-issues`/`list-gate-issues` (run `./bin/cadre sdlc --help`). If
missing, tell the human a kernel upgrade is needed and stop.

Reuse the GitLab project path (`namespace/project`) and the bot/service
account username (`--as-bot`) too if already established earlier in this
conversation. Otherwise ask for them. Never guess either value.

## Step 1 — Check what already exists

Run:

```sh
./bin/cadre sdlc list-gate-issues --root <path> --task-id <task-id>
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
./bin/cadre sdlc create-gate-issues --root <path> --task-id <task-id> \
  --project-path <namespace/project> --as-bot <bot-username> \
  [--gates <G_id,...>]
```

Parse the JSON yourself. Summarize in plain language, per gate: which gate
issues would be created vs. reused, and for each approval issue, **who it
would be assigned to** (the resolved GitLab username) — this is the moment
the human needs to actually see and confirm real names/usernames before
anything is posted to GitLab, not skip past. Also surface plainly:

- Any `refusals` (an authority couldn't be resolved to a GitLab account, or a
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
./bin/cadre sdlc create-gate-issues --root <path> --task-id <task-id> \
  --project-path <namespace/project> --as-bot <bot-username> \
  [--gates <G_id,...>] --apply --plan-digest <digest>
```

If the kernel reports the digest is stale (something changed between dry-run
and apply — an authority's GitLab binding, a rationale, gate status), do not
retry with a stale value or guess around it: re-run Step 3's dry-run, show
the human what changed, and get fresh confirmation before applying again.

Parse the result. Report plainly: which issues were created, which were
reused (already existed), which were refused (and why, per gate/authority),
and any assignee drift detected on a reused issue (see Step 6).

## Step 5 — Translate refusal reason codes

Never show raw reason codes; translate them:

- `authority-unknown` — that role has no entry in `.agentic-sdlc/authorities.json`
  yet; point back at `lifecycle-onboarding-gitlab`'s Step 4.
- `authority-unassigned` — the role exists but has no one assigned; same
  pointer.
- `no-gitlab-binding` — the assigned person's identity isn't in GitLab-username
  form (e.g. it's a bare email or a GitHub identity); they need a
  `gitlab_username` set for that authority in `authorities.json`.
- `gitlab-user-unresolved` — no active GitLab account matches that username on
  this instance; check for a typo or a deactivated account.
- `gitlab-user-ambiguous` — more than one account matched; needs human
  resolution, do not guess which one.
- `applicability-unknown` — the run record can't yet tell whether this
  authority applies to this gate; resolve the authority assignment first.
- `self-approval` — the resolved person is a preparer or independent verifier
  for this gate; a different, independent person needs to be assigned that
  role before an approval issue can be created for them.

A non-empty refusal list does not mean the whole run failed — report exactly
which specific gates/authorities succeeded, were skipped, and were refused,
never collapse this into a single pass/fail statement.

## Step 6 — Assignee drift on re-runs

If a reused approval issue's current GitLab assignee no longer matches the
authority's current resolved username (someone edited `authorities.json`, or
someone manually reassigned the issue in GitLab), the kernel reports this as
drift rather than silently changing anything. Tell the human plainly what
changed and ask whether they want it corrected — only re-run with
`--reconcile-assignees` if they explicitly say yes; never pass that flag
proactively.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never run `--apply` without the human having explicitly seen and confirmed
  the dry-run's assignments first — this is the one hard rule of this skill.
- Never fabricate a project path, bot username, gate list, or plan digest.
- A created or closed GitLab issue is never itself approval evidence — always
  correct a human who implies otherwise, and point them at `lifecycle-review-generic-gitlab`/
  `lifecycle-review-gitlab` for actually recording a decision.
- Summarize outcomes in prose after each step.
