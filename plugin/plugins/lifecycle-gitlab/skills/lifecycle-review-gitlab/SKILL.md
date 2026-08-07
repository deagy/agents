---
name: lifecycle-review-gitlab
description: Conversationally record a human's approve/reject/request-changes decision for an Agentic SDLC lifecycle gate (G1-G10) sourced from a real GitLab MR approval, for a human who does not want to touch a CLI or JSON directly. Use when a user asks to "approve this gate from the GitLab approval," "record my MR approval as the gate decision," or otherwise has an actual GitLab merge request approval to cite for a project already onboarded with lifecycle-onboarding-gitlab. If they don't have a GitLab approval to cite, use the bundled generic lifecycle-review-generic-gitlab skill instead.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# Lifecycle review (GitLab)

Use this skill instead of the bundled generic `lifecycle-review-generic-gitlab`
skill only when the human has a real GitLab merge request approval to cite as
their gate-decision evidence — it drives `agentic-sdlc approve-from-gitlab`/
`approve-from-gitlab-mr` (both require an actual GitLab MR approval; neither
is a substitute for `decide` when no such approval exists). If they don't
have one, use the generic `lifecycle-review-generic-gitlab` skill's `decide`
flow instead — do not fabricate or guess at MR/approval details to force this
skill to apply.

See `../../../../suite/docs/lifecycle-and-plugin-operations.md`'s
"GitHub-backed human approvals" section for the shape of this contract (the
kernel's GitLab commands mirror it one for one — same gate/role/evidence
model, GitLab-flavored source fields).

## Before you start

If the target root and task-id were already established earlier in this
conversation, reuse them rather than re-asking. Otherwise, confirm the
target root (`.` if you are already working inside it) and confirm
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists for the task
they mean (a quick local check of whether `.agentic-sdlc/runs/<task-id>/`
exists is a reasonable first move) — if the project has never been onboarded
or planned, stop and point them at the `lifecycle-onboarding-gitlab` skill (setup)
or `cadre sdlc plan` first. Never assume or guess a root or task-id you
haven't actually seen stated or confirmed in this conversation.

Check that the installed `agentic-sdlc` kernel actually has
`approve-from-gitlab`/`approve-from-gitlab-mr` (run `./bin/cadre sdlc --help`
and look for them in the subcommand list). If missing, tell the human a
kernel upgrade is needed and stop — do not silently fall back to `decide` or
`invalidate` as a workaround without telling them what you're doing and why.

Prefer `./bin/cadre sdlc ...` over the bare `agentic-sdlc` binary, so this
suite's own provider profile resolves.

## Step 1 — Find the task and the gate

Ask which task/run this is about only if it isn't already established from
earlier in this conversation — reuse it otherwise, never re-ask for
something you were already told. Run:

```sh
./bin/cadre sdlc status --root <path> --task-id <task-id>
```

Parse the JSON yourself. Summarize the current gate in plain language using
this mapping (same as `lifecycle-onboarding-gitlab`'s gate/phase vocabulary):

| Gate | Plain name |
| --- | --- |
| G1 | Intent |
| G2 | Requirements Baseline |
| G3 | Architecture |
| G4 | Governance and Data |
| G5 | Security and Crypto |
| G6 | Verification and Test |
| G7 | Evidence |
| G8 | Release Readiness |
| G9 | Deployment Authorization |
| G10 | Runtime Conformance |

If the human names a gate directly, map their words to the `G<N>` id
yourself. If they don't name one, default to whichever gate `status` reports
as next awaiting a decision.

## Step 2 — Confirm who is deciding, and refuse on their behalf if it isn't them

Read that gate's `authority_requirements` from
`.agentic-sdlc/runs/<task-id>/run-record.json` — only ask about roles the
gate actually requires. Ask the human's role in plain language, reusing
`lifecycle-onboarding-gitlab`'s Step 4 role table.

Look up that role's assigned identity in `.agentic-sdlc/authorities.json`.
Both commands below refuse to record an approval from anyone other than the
exact assigned identity, and also refuse if that identity is a preparer or
the independent verifier for this gate (self-approval). Do not try to work
around either refusal — tell the human plainly who the assigned authority
is, or that a different, independent person needs to make this call.

## Step 3 — Which command: prepared evidence, or fetch from the MR?

Ask the human whether they already know the specific GitLab approval's
details (approval id, approver's username, commit SHA), or would rather you
fetch the approved MR approval directly:

- **They have the approval details already** (or you're recording evidence a
  colleague reported to you) → `approve-from-gitlab` (Step 4a).
- **They just want to point at an MR and have you find the approved
  approval** → `approve-from-gitlab-mr`, which fails closed if it can't find
  a matching approved approval on that MR (Step 4b).

## Step 4a — approve-from-gitlab (prepared evidence)

Ask for: the GitLab project path (`namespace/project`), the MR internal ID
(iid), the GitLab approval id, the approver's GitLab username, and the
commit SHA the approval covered. Then run:

```sh
./bin/cadre sdlc approve-from-gitlab --root <path> --task-id <task-id> \
  --gate <G_id> --role <role> --project-path <namespace/project> \
  --mr-iid <iid> --approval-id <approval-id> \
  --approver-username <username> --commit-sha <sha> \
  [--decided-at <RFC3339>]
```

## Step 4b — approve-from-gitlab-mr (fetch from the MR)

Ask for: the GitLab project path (`namespace/project`) and the MR internal ID
(iid). Then run:

```sh
./bin/cadre sdlc approve-from-gitlab-mr --root <path> --task-id <task-id> \
  --gate <G_id> --role <role> --project-path <namespace/project> \
  --mr-iid <iid> [--approver-username <username>] [--commit-sha <sha>]
```

`--approver-username` defaults to the authority's GitLab binding if omitted;
`--commit-sha` narrows which approval counts if the MR has more than one and
the human wants a specific one.

## Step 5 — Report the outcome

Parse the returned JSON yourself. Report the outcome in one plain sentence
("Recorded — Architecture is now approved, sourced from MR !42's approval"),
never the raw JSON, unless they ask to see it.

## Step 6 — Translate errors, don't just print them

If the command exits non-zero, translate the `error` message, for example:

- `"actor <id> does not match assigned authority <id> for role <role>"` →
  re-explain who the assigned decision-maker actually is (Step 2).
- `"... is a preparer for <gate>; cannot decide on own work"` / `"... is the
  independent verifier for <gate>; cannot also decide"` → explain plainly
  that they can't sign off on their own work here.
- `"<gate> does not require authority role <role>"` → re-ask Step 2's role
  question.
- `"authority <role> is not assigned"` → this role has no one assigned yet;
  point back at `lifecycle-onboarding-gitlab`'s Step 4.
- An `approve-from-gitlab-mr` failure to find a matching approved approval →
  tell the human plainly, and offer `approve-from-gitlab` (Step 4a) with
  details they supply directly instead.

## Throughout

- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never let an actor-identity or self-decision refusal be worked around
  silently.
- Never fabricate an approval id, approver username, or commit SHA — if the
  human doesn't have these and doesn't want you to fetch them, use the
  generic `lifecycle-review-generic-gitlab` skill's `decide` flow instead.
- Summarize the outcome in prose after each decision.
