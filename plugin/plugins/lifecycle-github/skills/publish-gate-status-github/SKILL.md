---
name: publish-gate-status-github
description: Conversationally publish (and idempotently update in place on re-run) a one-way, read-only gate-status summary comment on a task's GitHub PR, via publish-gate-status/list-gate-status, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "post gate status on this PR," "update the gate-status comment," "show reviewers the current gate table on GitHub," or "keep the PR's gate summary current" for a project already onboarded with lifecycle-onboarding-github. This is unrelated to lifecycle-review-github: it never records or reads back an approval, it only posts a diagnostics summary.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# Publish gate status (GitHub)

Use this skill to drive `agentic-sdlc publish-gate-status` through a
plain-language conversation. It posts a single comment on a task's GitHub PR
summarizing all ten lifecycle gates' status (gate table, current phase, and a
reduced re-entry count), and updates that same comment in place on every
later re-run rather than posting duplicates.

**This comment is not an approval and is never read back.** The rendered
comment says so explicitly, and `agentic-sdlc` never reads the comment, its
reactions, or its replies back into gate state — there is no
"approve-from-this-comment" path and there never will be. Gate approval
remains exclusively `agentic-sdlc decide` / `approve-from-github-pr`, against
an external approval record. Reinforce this yourself whenever you report the
outcome to the human — never let them treat "I posted the gate-status
comment" as if it were a review action. This is the same posture
`create-github-gate-issues` takes toward the GitHub issues it creates.

Content is deliberately minimal: the gate table, current phase, and a count
of re-entries (never raw identity or rationale text). Do not promise the
human any more detail than that in your summaries.

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-github` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`publish-gate-status`/`list-gate-status` (run `./bin/cadre sdlc --help`). If
missing, tell the human a kernel upgrade is needed and stop.

Reuse the repository, PR number, bot username, and classification too if
they were already established earlier in this conversation. For anything
still missing, ask for it, and never fabricate:

- the GitHub repository (`owner/name`),
- the pull request number,
- the bot/service account username (`--as-bot`) the kernel should verify
  itself as before posting anything, and
- the task's classification, to pass as `--allow-classification` (it must
  exactly match the task's recorded classification or the command refuses).

## Step 1 — See what's already there (optional)

If the human wants a quick look without touching GitHub at all, you can run:

```sh
./bin/cadre sdlc list-gate-status --root <path> --task-id <task-id>
```

This is zero-network and reads only the local sidecar ledger, so it can be
stale relative to what's actually on the PR — mention that if you use it.
It's a convenience, not a required step.

## Step 2 — Preview (optional, no ceremony)

Unlike `create-github-gate-issues`, there's no plan-digest handshake here and
nothing gets assigned to anyone, so a dry-run isn't a mandatory gate — it's
just useful to preview. `--dry-run` is also the command's default:

```sh
./bin/cadre sdlc publish-gate-status --root <path> --task-id <task-id> \
  --forge github --repo <owner/name> --pr <number> \
  --as-bot <bot-username> --allow-classification <classification>
```

Parse the JSON and tell the human, in plain language, what would happen:
`create` (no matching comment yet), `update` (an existing comment authored by
the bot would be refreshed), or `unchanged` (the rendered body already
matches what's posted — nothing would actually change). If you skip this
step, that's fine, but make sure the human has still confirmed the repo/PR
and task named above before you move to Step 3.

## Step 3 — Apply

```sh
./bin/cadre sdlc publish-gate-status --root <path> --task-id <task-id> \
  --forge github --repo <owner/name> --pr <number> \
  --as-bot <bot-username> --allow-classification <classification> --apply
```

Parse the JSON result and report plainly:

- the resolved action (`created`, `updated`, or `unchanged`),
- the comment id if one was returned, and
- restate the non-approval disclaimer above in your own words.

Re-running this later to keep the comment current is expected and
low-friction — encourage that habit rather than treating every re-run as a
fresh, heavyweight confirmation cycle. The one thing that must never be
skipped is the human having seen the actual repo/PR and task-id you're about
to post to, named explicitly, before you `--apply`.

## Step 4 — Translate errors

Never show a raw error string; translate it:

- **more than one matching comment found** (`multiple_matches`) — blocked,
  needs human resolution. Do not guess which one is "correct" or delete
  either; tell the human to resolve it directly on GitHub.
- **a matching comment exists but wasn't authored by the verified bot**
  (`foreign_author`) — blocked. Never edit or overwrite a comment this tool
  didn't post itself, even if it looks similar.
- **more than 1,000 comments scanned without finding a definitive answer**
  (page-cap exceeded) — blocked (exit 2) by design: there could be a match on
  an unfetched page, so the tool refuses to guess rather than risk a
  duplicate or a silent overwrite.
- **lock held** — another `publish-gate-status`/`create-gate-issues`-family
  run for this task/forge is in progress (or a previous run crashed and left
  a stale lock). Do not pass `--break-lock` unless the human explicitly
  confirms no other run is actually in flight.
- **classification mismatch** — the `--allow-classification` value you
  supplied doesn't exactly match the task's recorded classification; ask the
  human for the correct value rather than guessing or omitting it.
- **`--as-bot` identity mismatch** — the GitHub token in use doesn't actually
  belong to the username you passed; confirm the intended bot account with
  the human rather than retrying with a different guess.
- **post-write verification failed** (`suspect` in the local ledger) — the
  comment that was just created/updated didn't come back with the expected
  author or body when re-fetched. Tell the human this needs manual
  inspection on GitHub; do not retry blindly.

A blocked classification is not a partial success — the comment was not
created or updated. Say so plainly.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never fabricate a repo, PR number, bot username, or classification value.
- Never run `--apply` before the human has seen the repo/PR and task-id you
  intend to post to, named explicitly — that is the one hard rule of this
  skill, even without a plan-digest handshake.
- Always restate that the posted comment is not approval evidence and is
  never read back by `agentic-sdlc` — correct a human who implies otherwise,
  and point them at `lifecycle-review-generic-github`/`lifecycle-review-github` for actually
  recording a gate decision.
- Summarize outcomes in prose after each step.
