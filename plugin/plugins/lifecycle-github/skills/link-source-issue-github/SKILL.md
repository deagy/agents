---
name: link-source-issue-github
description: Conversationally record a real GitHub issue as the recorded source for a task's G1 (Intent) or G2 (Requirements Baseline) gate, via link-intent-from-github-issue/link-requirements-from-github-issue, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "link this GitHub issue as the source for G1/Intent," "record this issue as the requirements source," or "attach a GitHub issue to G1/G2" for a project already onboarded with lifecycle-onboarding-github. This only ever applies to G1 or G2, and only records a source, not an approval — for approvals from a GitHub PR review use lifecycle-review-github, and for any other gate use lifecycle-review-generic-github.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# Link source issue (GitHub)

Use this skill to drive `agentic-sdlc link-intent-from-github-issue` /
`link-requirements-from-github-issue` through a plain-language conversation.
These commands fetch one real GitHub issue and record it as the recorded
*source* for a task's G1 (Intent) or G2 (Requirements Baseline) gate.

**This is not approval evidence.** Neither command ever touches
`human_approvals` or a gate's `status` — recording a source issue link is a
separate, lower-stakes action than deciding a gate. This mirrors the same
disclaimer `create-github-gate-issues` carries for its own artifacts: closing or
commenting on an issue is never itself an approval, and neither is linking
one as a source. For actually recording a gate decision, use
`lifecycle-review-generic-github`/`lifecycle-review-github` instead.

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-github` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`link-intent-from-github-issue`/`link-requirements-from-github-issue` (run
`./bin/cadre sdlc --help`). If missing, tell the human a kernel upgrade is
needed and stop.

## Step 1 — Which gate: G1 or G2 only

Ask which gate this is for. **Only G1 (Intent) and G2 (Requirements
Baseline) accept a source issue link** — no other gate does. If the human
names any other gate (G3–G10), tell them plainly this skill only applies to
G1/G2, and point them at `lifecycle-onboarding-github` (setup) or `lifecycle-review-generic-github`
(recording a decision for any gate) instead. Do not attempt to force a link
for a gate this skill doesn't cover.

Map their answer to the command you'll use in Step 4:

- G1 (Intent) → `link-intent-from-github-issue`
- G2 (Requirements Baseline) → `link-requirements-from-github-issue`

## Step 2 — Who is recording this, and what issue

Read the target gate's `authority_requirements` from
`.agentic-sdlc/runs/<task-id>/run-record.json`, and ask the human's role in
plain language (reusing `lifecycle-onboarding-github`'s Step 4 role table). The
kernel only accepts a link from the exact assigned authority for that
role/gate — do not guess or substitute a different role.

Ask for the GitHub repository (`owner/repo`) and the issue number, unless
they were already established earlier in this conversation, in which case
reuse them. Never fabricate either value — if the human doesn't have them
handy and they haven't been stated already, stop and ask rather than
guessing.

## Step 3 — Show what will happen, then confirm

This is a one-way, low-ceremony action — it fetches one issue and records
one link, nothing more — so it does not need a dry-run/apply two-phase flow
the way `create-github-gate-issues` does. But it is still an external-state read
plus a repository-state write, so tell the human plainly, before running
anything:

- which gate this will be recorded against (G1/Intent or G2/Requirements
  Baseline)
- the exact repository and issue number
- that if this task's gate already has a recorded source, this **replaces**
  it rather than adding alongside it

If you're able to look up the issue's title first (e.g. via `gh issue view`)
show that too so the human can confirm it's the issue they mean. Get an
explicit go-ahead before running the link command.

## Step 4 — Run the link command

```sh
./bin/cadre sdlc link-intent-from-github-issue --root <path> --task-id <task-id> \
  --role <role> --repo <owner/repo> --issue-number <number>
```

or, for G2:

```sh
./bin/cadre sdlc link-requirements-from-github-issue --root <path> --task-id <task-id> \
  --role <role> --repo <owner/repo> --issue-number <number>
```

## Step 5 — Report the outcome

Parse the returned JSON yourself. Report the outcome in one plain sentence
("Recorded — issue #42 ('Add rate limiting') is now the source for
Requirements Baseline"), never the raw JSON, unless they ask to see it.

## Step 6 — Translate errors, don't just print them

If the command exits non-zero, the kernel returns `{"error": "..."}`. Never
show that raw string; translate it:

- `"<gate> does not require authority role <role>"` → re-ask Step 2's role
  question; that role isn't part of this gate's requirements.
- `"<gate> authority role <role> is not applicable"` → that role doesn't
  apply to this gate for this task; re-check with the human.
- `"authority <role> is not assigned"` → this role has no one assigned yet;
  point back at `lifecycle-onboarding-github`'s Step 4.
- `"unable to fetch GitHub issue for <repo> issue <number>: ..."` → the
  issue doesn't exist, the repo is wrong, or the GitHub API call failed
  (auth, network, rate limit). Tell the human plainly which of these seems
  likely and ask them to double-check the repo/issue number, don't show the
  raw API error text unless they ask.
- `"GitHub issue <repo>#<number> response is missing a title"` /
  `"... unrecognized state"` → an unexpected API response; tell them plainly
  something looked wrong with the issue data returned and offer to retry.
- `"unknown gate in run record"` / `"unknown authority role"` → something is
  inconsistent with this task's run record or authorities; do not guess,
  surface it plainly and suggest checking `lifecycle-onboarding-github`'s setup.

A gate other than G1/G2 will never reach this command at all — that's
handled by Step 1's up-front check, not a runtime error from the kernel.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never fabricate a repository, issue number, task id, or role.
- A recorded source issue link is never approval evidence — always correct a
  human who implies otherwise, and point them at `lifecycle-review-generic-github`/
  `lifecycle-review-github` for actually recording a gate decision.
- Relinking replaces the gate's prior recorded source; it does not add a
  second one. Make sure the human understands this before Step 4 if a prior
  source might already exist.
- Summarize the outcome in prose after each step.
