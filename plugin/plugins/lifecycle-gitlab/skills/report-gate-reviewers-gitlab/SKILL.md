---
name: report-gate-reviewers-gitlab
description: Conversationally report which GitLab usernames would be set as MR reviewers for a task's lifecycle gates, for a human who does not want to touch a CLI or JSON directly. Use when a user asks "who should review this gate on GitLab," "who do I need to add as a reviewer on this MR," or "check reviewer status for this MR" for a project already onboarded with lifecycle-onboarding-gitlab. This is read-only/reporting only — it never sets reviewer_ids; use it to prepare what to do manually in the GitLab UI.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.

# Report GitLab MR reviewer candidates

Use this skill to drive `agentic-sdlc request-gate-reviewers-gitlab` end to
end through a plain-language conversation. It reports which GitLab usernames
*would* be set as MR reviewers (GitLab's lightweight, per-MR `reviewers`
field — the direct analog of GitHub's requested-reviewers, not GitLab's
separate quorum-based approval-rules mechanism) for a task's lifecycle
gates, derived from each eligible gate's `authority_requirements[]` and
`authorities.json`, and classifies each candidate against the MR's live
state.

This is the GitLab sibling of `report-gate-reviewers-github`, not the same
skill reused across forges — the two forges' classification vocabularies are
genuinely different (see Step 2 and the staleness note below), so do not
conflate their reason codes or assume this skill's output maps one-to-one
onto the GitHub version's.

## Say this up front, before running anything

**This command only reports candidates — it does not set MR reviewers.**
There is no `--apply` flag and no write path in this kernel version at all:
setting MR reviewers needs a GitLab API token with write scope, so that write
capability has not been built pending an explicit human decision on that
permission escalation. Tell the human this plainly before running the
report, and again when you hand back the summary: if they want reviewers
actually set, they need to do it manually in the GitLab UI (or via
`glab mr update <iid> --reviewer <username>` themselves, outside this skill)
using this report as their checklist.

## Before you start

If the target root and task-id were already established earlier in this
conversation, reuse them rather than re-asking. Otherwise, confirm the
target root (`.` if already working inside it) and confirm
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists for the task
(a quick local check of whether `.agentic-sdlc/runs/<task-id>/` exists is a
reasonable first move) — if the project has never been onboarded or planned,
point them at the `lifecycle-onboarding-gitlab` skill (setup) or `cadre sdlc plan`
first.

Check that the installed `agentic-sdlc` kernel actually has
`request-gate-reviewers-gitlab` (run `./bin/cadre sdlc --help` and look for
it in the subcommand list). If missing, tell the human a kernel upgrade is
needed and stop — do not improvise a substitute, and do not fall back to
`request-gate-reviewers` (GitHub) for a GitLab MR.

Prefer `./bin/cadre sdlc ...` over the bare `agentic-sdlc` binary, so this
suite's own provider profile resolves.

The same rule applies to everything below: reuse a value already established
earlier in this conversation rather than re-asking for it. Ask for, and
never fabricate or guess, whatever is still genuinely unknown:

- The GitLab project path (`namespace/project`).
- The merge request internal ID (`--mr-iid`) — this command never
  auto-discovers an MR, it must be given explicitly.
- The bot/service account username to verify as (`--as-bot`), if the human
  has one they use for this kind of check.
- The task's classification, so `--allow-classification` can be supplied
  exactly matching the run record (`cadre sdlc status` shows it if unsure).
- Optionally, a gate subset (`--gates G3,G9`); default to all eligible gates
  if they have no preference. Do not invent a subset.

## Step 1 — Run the report

```sh
./bin/cadre sdlc request-gate-reviewers-gitlab --root <path> --task-id <task-id> \
  --project-path <namespace/project> --mr-iid <iid> --as-bot <bot-username> \
  --allow-classification <classification> [--gates <G_id,...>]
```

Exit code `0` means the report completed with no refusals. Exit code `2`
means the report completed but contains refusals or `withheld-conflict`
entries — this is informational, not a failure of the report itself; still
parse and show the JSON. Exit code `1` means a structural problem prevented
building the report at all (MR not found/closed/merged, project-path
mismatch, or the verified `--as-bot` identity didn't match) — translate the
error message plainly rather than retrying blindly.

## Step 2 — Summarize plainly, per username

Parse the JSON yourself; never dump it raw unless asked. For each entry in
`reviewers`, report in plain language:

- **Who** (the GitLab username) and **why** (which gates/roles motivate them
  — list each `motivations[].gate_id` plus its plain gate name from the
  table below, and the `role`).
- **Current status**, translating `classification`:
  - `already-reviewer` — GitLab already has them set as an MR reviewer; no
    action needed.
  - `already-approved` — they've already approved this MR. **Unlike the
    GitHub version, there is no way to tell whether this approval is
    against the MR's current head commit or an older one** — GitLab's
    approvals API has no per-approver commit field (see the note below), so
    treat `already-approved` as "has approved at some point," not "approved
    the latest changes," and say so if the human asks about currency.
  - `to-request` — not yet set as a reviewer and hasn't approved; this is a
    candidate the human may want to add in the GitLab UI.
  - `withheld-conflict` — see Step 3.
  - `gitlab-user-unresolved` — the username doesn't resolve to any active
    GitLab account (typo, deactivated/blocked account, or it never existed).
  - `gitlab-user-ambiguous` — GitLab's username lookup is search-based, not
    exact-match like GitHub's, and more than one active account matched;
    this needs manual disambiguation on GitLab, not a guess.

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

### Why there is no "review-stale" status here

The GitHub version of this report can tell you a review is stale (approved
an older commit than the PR's current head) because GitHub records a commit
id on every individual review. GitLab's merge-request approvals endpoint has
no equivalent per-approver field — it only exposes one commit SHA for the
whole MR, applied the same way to every approver, which is not reliable
enough to say who approved which version of the code. Rather than guess,
this report simply never produces a `review-stale`-equivalent status. If the
human needs to know whether an approval is current, tell them to check the
MR's own activity/commit history on GitLab directly.

## Step 3 — Explain "poisoning" for withheld-conflict entries

A GitLab MR reviewer assignment is MR-wide, not scoped to one gate. If a
username is refused for *any one* of its motivating gates on independence
grounds (`self-approval`, `mr-author-conflict`, or `actor-is-reviewer`),
that username is withheld from *all* of its motivations for this report,
even ones that would otherwise be clean. Explain this plainly, for example:

> "Alice would normally be asked to review for gates G3 and G6, but since
> she's a preparer on G9, none of her reviewer additions are being
> suggested — not even for G3 and G6."

Translate the `withheld_cause.reason` on each `withheld-conflict` entry:

- `self-approval` — the resolved person is a preparer or the independent
  verifier for that gate; reviewing here would mean signing off on their own
  work.
- `mr-author-conflict` — the resolved username is the MR's own author.
- `actor-is-reviewer` — the resolved username is the verified `--as-bot`
  identity itself.

## Step 4 — Explain other refusal reason codes

Never show raw reason codes; translate any entries in `refusals` (and note
that these are separate from `withheld-conflict` — a refusal explains why a
`(gate, authority)` pair never became a candidate at all, not why an
already-built candidate was withheld):

- `authority-unknown` — that role has no entry in
  `.agentic-sdlc/authorities.json` yet; point back at
  `lifecycle-onboarding-gitlab`'s Step 4.
- `authority-unassigned` — the role exists but has no one assigned; same
  pointer.
- `no-gitlab-binding` — the assigned person's identity isn't in GitLab
  username form; they need a GitLab identity binding set for that authority.
- `self-approval` / `mr-author-conflict` / `actor-is-reviewer` — see Step 3;
  these are the same independence reasons, reported here at the
  `(gate, authority)` level.
- `applicability-unknown` — the run record can't yet tell whether this
  authority applies to this gate.

A non-empty refusals list does not mean the whole report failed — report
exactly which usernames/gates were clean, withheld, or unresolved; never
collapse this into a single pass/fail statement.

## Step 5 — Hand back a checklist, not an action

Close by restating plainly: nothing was set on GitLab. If the human wants to
act on this, tell them to open the MR in the GitLab UI and add the
`to-request` usernames as reviewers themselves. Do not offer to do this for
them beyond what this skill's read-only report already covers.

## Throughout

- Never imply a reviewer was set — this command has no write path in this
  kernel version, full stop.
- Never fabricate a project path, MR iid, username, gate id, or
  classification value.
- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- Never present `already-approved` as if it guarantees the approval covers
  the MR's current changes — see the staleness note in Step 2.
- This report is advisory only — it is not gate-decision evidence and does
  not affect any gate's status. Point to `lifecycle-review-gitlab` for
  actually recording a decision.
- Summarize outcomes in prose after running the report.
