---
name: publish-gate-status-gitlab
description: Conversationally publish (and idempotently update in place on re-run) a one-way, read-only gate-status summary comment on a task's GitLab MR, via publish-gate-status/list-gate-status, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "post gate status on this MR," "update the gate-status note," "show reviewers the current gate table on GitLab," or "keep the MR's gate summary current" for a project already onboarded with lifecycle-onboarding-gitlab. This is unrelated to lifecycle-review-gitlab and gitlab-gate-tracking: it never records or reads back an approval and never creates assigned issues, it only posts a diagnostics summary note.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# Publish gate status (GitLab)

Use this skill to drive `agentic-sdlc publish-gate-status` through a
plain-language conversation. It posts a single note on a task's GitLab MR
summarizing all ten lifecycle gates' status (gate table, current phase, and a
reduced re-entry count), and updates that same note in place on every later
re-run rather than posting duplicates.

**This note is not an approval and is never read back.** The rendered note
says so explicitly, and `agentic-sdlc` never reads the note, its reactions,
or its replies back into gate state — there is no "approve-from-this-note"
path and there never will be. Gate approval remains exclusively
`agentic-sdlc decide` / `approve-from-gitlab-mr`, against an external
approval record. Reinforce this yourself whenever you report the outcome to
the human — never let them treat "I posted the gate-status note" as if it
were a review action. This is the same posture `gitlab-gate-tracking` takes
toward the tracking issues it creates, and this skill has no connection to
that one beyond both writing to GitLab.

Content is deliberately minimal: the gate table, current phase, and a count
of re-entries (never raw identity or rationale text). Do not promise the
human any more detail than that in your summaries.

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-gitlab` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`publish-gate-status`/`list-gate-status` (run `./bin/cadre sdlc --help`). If
missing, tell the human a kernel upgrade is needed and stop.

Reuse the project path, MR iid, bot username, and classification too if
they were already established earlier in this conversation. For anything
still missing, ask for it, and never fabricate:

- the GitLab project path (`namespace/project`),
- the merge request internal ID (`--mr-iid`),
- the bot/service account username (`--as-bot`) the kernel should verify
  itself as before posting anything, and
- the task's classification, to pass as `--allow-classification` (it must
  exactly match the task's recorded classification or the command refuses).

## Step 1 — See what's already there (optional)

If the human wants a quick look without touching GitLab at all, you can run:

```sh
./bin/cadre sdlc list-gate-status --root <path> --task-id <task-id>
```

This is zero-network and reads only the local sidecar ledger, so it can be
stale relative to what's actually on the MR — mention that if you use it.
It's a convenience, not a required step. (It has no `--forge` flag and
reports both forges' ledgers, so it may also show a stale GitHub entry if
this task was ever published there.)

## Step 2 — Preview (optional, no ceremony)

Unlike `gitlab-gate-tracking`, there's no plan-digest handshake here and
nothing gets assigned to anyone, so a dry-run isn't a mandatory gate — it's
just useful to preview. `--dry-run` is also the command's default:

```sh
./bin/cadre sdlc publish-gate-status --root <path> --task-id <task-id> \
  --forge gitlab --project-path <namespace/project> --mr-iid <iid> \
  --as-bot <bot-username> --allow-classification <classification>
```

Parse the JSON and tell the human, in plain language, what would happen:
`create` (no matching note yet), `update` (an existing note authored by the
bot would be refreshed), or `unchanged` (the rendered body already matches
what's posted — nothing would actually change). If you skip this step,
that's fine, but make sure the human has still confirmed the project/MR and
task named above before you move to Step 3.

## Step 3 — Apply

```sh
./bin/cadre sdlc publish-gate-status --root <path> --task-id <task-id> \
  --forge gitlab --project-path <namespace/project> --mr-iid <iid> \
  --as-bot <bot-username> --allow-classification <classification> --apply
```

Parse the JSON result and report plainly:

- the resolved action (`created`, `updated`, or `unchanged`),
- the note id if one was returned, and
- restate the non-approval disclaimer above in your own words.

Re-running this later to keep the note current is expected and
low-friction — encourage that habit rather than treating every re-run as a
fresh, heavyweight confirmation cycle. The one thing that must never be
skipped is the human having seen the actual project/MR and task-id you're
about to post to, named explicitly, before you `--apply`.

## Step 4 — Translate errors

Never show a raw error string; translate it:

- **more than one matching note found** (`multiple_matches`) — blocked,
  needs human resolution. Do not guess which one is "correct" or delete
  either; tell the human to resolve it directly on GitLab.
- **a matching note exists but wasn't authored by the verified bot**
  (`foreign_author`) — blocked. Never edit or overwrite a note this tool
  didn't post itself, even if it looks similar.
- **more than 1,000 notes scanned without finding a definitive answer**
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
- **`--as-bot` identity mismatch** — the GitLab token in use doesn't actually
  belong to the username you passed; confirm the intended bot account with
  the human rather than retrying with a different guess.
- **post-write verification failed** (`suspect` in the local ledger) — the
  note that was just created/updated didn't come back with the expected
  author or body when re-fetched. Tell the human this needs manual
  inspection on GitLab; do not retry blindly.

A blocked classification is not a partial success — the note was not created
or updated. Say so plainly.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never fabricate a project path, MR iid, bot username, or classification
  value.
- Never run `--apply` before the human has seen the project/MR and task-id
  you intend to post to, named explicitly — that is the one hard rule of
  this skill, even without a plan-digest handshake.
- Always restate that the posted note is not approval evidence and is never
  read back by `agentic-sdlc` — correct a human who implies otherwise, and
  point them at `lifecycle-review-generic-gitlab`/`lifecycle-review-gitlab` for actually
  recording a gate decision.
- Summarize outcomes in prose after each step.
