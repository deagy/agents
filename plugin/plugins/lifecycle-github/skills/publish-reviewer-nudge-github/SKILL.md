---
name: publish-reviewer-nudge-github
description: Conversationally publish (and idempotently update in place on re-run) an advisory GitHub PR comment suggesting reviewers for a task's lifecycle gates, via publish-reviewer-nudge/list-reviewer-nudge, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "nudge reviewers on this PR," "post a reviewer suggestion comment," or "let people know who should look at this" for a project already onboarded with lifecycle-onboarding-github. This posts a SUGGESTION comment only — it is not a formal review request and does not notify anyone; it is unrelated to report-gate-reviewers-github (the read-only report this reuses) and unrelated to publish-gate-status-github (a different comment, a different claim).
---

> Packaged suite note: when the current project has no local `roster/` tree,
> resolve suite files under `../../../../suite/roster/` relative to this
> `SKILL.md`. The packaged plugin is self-contained; do not look for the
> source checkout.

# Publish an advisory reviewer nudge (GitHub)

Use this skill to drive `agentic-sdlc publish-reviewer-nudge` through a
plain-language conversation. It posts a single comment on a task's GitHub PR
*suggesting* who a human might ask to review it, reusing
`request-gate-reviewers`'s own classification, and updates that same comment
in place on every later re-run rather than posting duplicates.

## Say this up front, before running anything — this is the most important part of this skill

**This posts a suggestion comment. It is not a review request, and it does
not ask, notify, or ping anyone.** `agentic-sdlc` has not requested a review
from anyone, and the people named in the comment have not been notified by
it being posted — the tool deliberately writes logins as plain text
(`` `login` ``), never as a GitHub `@`-mention, specifically so that posting
or updating the comment never itself triggers a GitHub notification to
anyone. If the human wants to actually, formally request a review, tell them
plainly: **they need to do that themselves in the GitHub UI** (or
`@`-mention someone directly, which does notify them — this tool never
does). Never describe this skill's action as "requesting a review," "asking
someone to review," "notifying reviewers," or "pinging" anyone — say
"suggesting" or "posting a nudge comment naming candidates" instead, and
correct the human if they use stronger language than that when describing
what just happened.

This exists specifically because actually requesting PR reviewers needs a
GitHub token scope (`Pull requests: write`) that has no narrower option and
also permits editing/closing PRs and changing labels — that write capability
has not been built pending an explicit human decision on that permission
escalation (see `report-gate-reviewers-github`, which remains the read-only
report this skill's underlying command reuses). This skill instead reuses
the comment-write capability `publish-gate-status-github` already uses
(`Issues: write` scope) to post a suggestion, not a request.

## Before you start

Reuse the target root and task-id if already established earlier in this
conversation — only ask if genuinely not yet known. Confirm that
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists (a quick local
check of whether `.agentic-sdlc/runs/<task-id>/` exists is a reasonable
first move) — if the project has never been onboarded or planned, point them
at `lifecycle-onboarding-github` or `cadre sdlc plan` first.

Check that the installed `agentic-sdlc` kernel actually has
`publish-reviewer-nudge`/`list-reviewer-nudge` (run `./bin/cadre sdlc --help`).
If missing, tell the human a kernel upgrade is needed and stop.

Prefer `./bin/cadre sdlc ...` over the bare `agentic-sdlc` binary, so this
suite's own provider profile resolves.

Reuse the repository, PR number, bot username, and classification too if
they were already established earlier in this conversation. For anything
still missing, ask for it, and never fabricate:

- the GitHub repository (`owner/name`),
- the pull request number — this command never auto-discovers a PR,
- the bot/service account username (`--as-bot`) the kernel should verify
  itself as before posting anything,
- the task's classification, to pass as `--allow-classification` (it must
  exactly match the task's recorded classification or the command refuses),
  and
- optionally, a gate subset (`--gates G3,G9`); default to all eligible gates
  if the human has no preference.

## Step 1 — See what's already there (optional)

If the human wants a quick look without touching GitHub at all, you can run:

```sh
./bin/cadre sdlc list-reviewer-nudge --root <path> --task-id <task-id>
```

This is zero-network and reads only the local sidecar ledger, so it can be
stale relative to what's actually on the PR — mention that if you use it.
It's a convenience, not a required step.

## Step 2 — Preview (optional, no ceremony)

There's no plan-digest handshake here, so a dry-run isn't a mandatory gate —
it's just useful to preview. `--dry-run` is also the command's default:

```sh
./bin/cadre sdlc publish-reviewer-nudge --root <path> --task-id <task-id> \
  --repo <owner/name> --pr <number> --as-bot <bot-username> \
  --allow-classification <classification> [--gates <G_id,...>]
```

Parse the JSON and tell the human, in plain language, what would happen:
`create` (no matching comment yet), `update` (an existing comment authored by
the bot would be refreshed), or `unchanged` (the rendered body already
matches what's posted — nothing would actually change). Also tell them
plainly who would be named (`nudged_logins`) and how many additional
reviewers exist but are withheld from the comment due to a gate-independence
conflict (`withheld_count`) — never name a withheld login yourself either,
even in conversation; if the human wants to know who and why, point them at
`report-gate-reviewers-github`'s full report, run locally.

## Step 3 — Apply

```sh
./bin/cadre sdlc publish-reviewer-nudge --root <path> --task-id <task-id> \
  --repo <owner/name> --pr <number> --as-bot <bot-username> \
  --allow-classification <classification> --apply [--gates <G_id,...>]
```

Parse the JSON result and report plainly:

- the resolved action (`created`, `updated`, or `unchanged`),
- the comment id if one was returned,
- who was named (`nudged_logins`) and the withheld count, and
- restate the "suggestion, not a request; nobody notified" framing above in
  your own words — this is not optional, do it every time.

Re-running this later to keep the comment current is expected and
low-friction — encourage that habit rather than treating every re-run as a
fresh, heavyweight confirmation cycle. The one thing that must never be
skipped is the human having seen the actual repo/PR and task-id you're about
to post to, named explicitly, before you `--apply`.

## Step 4 — Translate errors

Never show a raw error string; translate it. This shares its comment-write
mechanics with `publish-gate-status-github`, so the same failure modes
apply:

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
- **lock held** — another `publish-reviewer-nudge`/`publish-gate-status`-family
  run for this task is in progress (or a previous run crashed and left a
  stale lock). Do not pass `--break-lock` unless the human explicitly
  confirms no other run is actually in flight.
- **classification mismatch** — the `--allow-classification` value you
  supplied doesn't exactly match the task's recorded classification; ask the
  human for the correct value rather than guessing or omitting it.
- **`--as-bot` identity mismatch** — the GitHub token in use doesn't actually
  belong to the username you passed; confirm the intended bot account with
  the human rather than retrying with a different guess.
- **PR not found/closed/merged, or repo mismatch** — this command reuses
  `request-gate-reviewers`'s own PR validation; translate the message
  plainly rather than retrying blindly.
- **post-write verification failed** (`suspect` in the local ledger) — the
  comment that was just created/updated didn't come back with the expected
  author or body when re-fetched. Tell the human this needs manual
  inspection on GitHub; do not retry blindly.

A blocked classification is not a partial success — the comment was not
created or updated. Say so plainly.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never fabricate a repo, PR number, bot username, gate id, or
  classification value.
- Never run `--apply` before the human has seen the repo/PR and task-id you
  intend to post to, named explicitly — that is the one hard rule of this
  skill, even without a plan-digest handshake.
- Never name a `withheld-conflict` login in conversation, in a summary, or
  anywhere else derived from this command's output — the posted comment
  itself only reports a count for exactly this reason, and your summary must
  keep that same restraint.
- Always, every time you report an outcome, restate that this is a
  suggestion — never a request, and never a notification to anyone. If the
  human describes the outcome as "I asked so-and-so to review" or "I
  requested reviews," correct them: nobody was asked or notified; they can
  do that themselves in GitHub's UI if they want it to actually happen.
- This is unrelated to `report-gate-reviewers-github` (the read-only report
  this reuses) and unrelated to `publish-gate-status-github` (a different
  comment, under a different marker, making a different claim — gate status,
  not reviewer suggestions). Point to `lifecycle-review-github` for actually
  recording a gate decision; this skill never does that.
- Summarize outcomes in prose after each step.
