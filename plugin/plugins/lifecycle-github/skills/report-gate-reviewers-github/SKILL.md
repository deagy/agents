---
name: report-gate-reviewers-github
description: Conversationally report which GitHub logins would be requested as PR reviewers for a task's lifecycle gates, for a human who does not want to touch a CLI or JSON directly. Use when a user asks "who should review this gate on GitHub," "who do I need to request reviews from," or "check reviewer status for this PR" for a project already onboarded with lifecycle-onboarding-github. This is read-only/reporting only — it never posts a review request; use it to prepare what to do manually in the GitHub UI.
---

> Packaged suite note: when the current project has no local `roster/` tree,
> resolve suite files under `../../../../suite/roster/` relative to this
> `SKILL.md`. The packaged plugin is self-contained; do not look for the
> source checkout.

# Report GitHub PR reviewer candidates

Use this skill to drive `agentic-sdlc request-gate-reviewers` end to end
through a plain-language conversation. It reports which GitHub logins *would*
be requested as PR reviewers for a task's lifecycle gates, derived from each
eligible gate's `authority_requirements[]` and `authorities.json`, and
classifies each candidate against the PR's live state.

## Say this up front, before running anything

**This command only reports candidates — it does not request any reviews.**
There is no `--apply` flag and no write path in this kernel version at all:
requesting PR reviewers needs a GitHub token scope (`Pull requests: write`)
that has no narrower option and also permits editing/closing PRs and
changing labels, so that write capability has not been built pending an
explicit human decision on that permission escalation. Tell the human this
plainly before running the report, and again when you hand back the summary:
if they want reviewers actually requested, they need to do it manually in
the GitHub UI (or via `gh pr edit --add-reviewer <login>` themselves, outside
this skill) using this report as their checklist.

## Before you start

If the target root and task-id were already established earlier in this
conversation, reuse them rather than re-asking. Otherwise, confirm the
target root (`.` if already working inside it) and confirm
`.agentic-sdlc/runs/<task-id>/run-record.json` already exists for the task
(a quick local check of whether `.agentic-sdlc/runs/<task-id>/` exists is a
reasonable first move) — if the project has never been onboarded or planned,
point them at the `lifecycle-onboarding-github` skill (setup) or `cadre sdlc plan`
first.

Check that the installed `agentic-sdlc` kernel actually has
`request-gate-reviewers` (run `./bin/cadre sdlc --help` and look for it in
the subcommand list). If missing, tell the human a kernel upgrade is needed
and stop — do not improvise a substitute.

Prefer `./bin/cadre sdlc ...` over the bare `agentic-sdlc` binary, so this
suite's own provider profile resolves.

The same rule applies to everything below: reuse a value already established
earlier in this conversation rather than re-asking for it. Ask for, and
never fabricate or guess, whatever is still genuinely unknown:

- The GitHub repository (`owner/repo`).
- The PR number — this command never auto-discovers a PR, it must be given
  explicitly.
- The bot/service account login to verify as (`--as-bot`), if the human has
  one they use for this kind of check.
- The task's classification, so `--allow-classification` can be supplied
  exactly matching the run record (`cadre sdlc status` shows it if unsure).
- Optionally, a gate subset (`--gates G3,G9`); default to all eligible gates
  if they have no preference. Do not invent a subset.

## Step 1 — Run the report

```sh
./bin/cadre sdlc request-gate-reviewers --root <path> --task-id <task-id> \
  --repo <owner/repo> --pr <number> --as-bot <bot-login> \
  --allow-classification <classification> [--gates <G_id,...>]
```

Exit code `0` means the report completed with no refusals. Exit code `2`
means the report completed but contains refusals or `withheld-conflict`
entries — this is informational, not a failure of the report itself; still
parse and show the JSON. Exit code `1` means a structural problem prevented
building the report at all (PR not found/closed/merged, repo mismatch, or
the verified `--as-bot` identity didn't match) — translate the error message
plainly rather than retrying blindly.

## Step 2 — Summarize plainly, per login

Parse the JSON yourself; never dump it raw unless asked. For each entry in
`reviewers`, report in plain language:

- **Who** (the GitHub login) and **why** (which gates/roles motivate them —
  list each `motivations[].gate_id` plus its plain gate name from the table
  below, and the `role`).
- **Current status**, translating `classification`:
  - `already-requested` — GitHub already has a pending review request out to
    them; no action needed.
  - `already-reviewed` — they've already reviewed at the PR's current head
    commit; no re-ping needed.
  - `review-stale` — they reviewed, but on an older commit than the PR's
    current head; a fresh look may be warranted (distinguish this clearly
    from `already-reviewed` — do not collapse the two).
  - `to-request` — no request or review yet; this is a candidate the human
    may want to request in the GitHub UI.
  - `withheld-conflict` — see Step 3.
  - `github-user-unresolved` — the login doesn't resolve to a real GitHub
    account (typo, or the account no longer exists).
  - `not-a-collaborator` — the login is a real GitHub account but isn't a
    collaborator on this repository, so GitHub would refuse a review
    request for them.

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

## Step 3 — Explain "poisoning" for withheld-conflict entries

A GitHub review request is PR-wide, not scoped to one gate. If a login is
refused for *any one* of its motivating gates on independence grounds
(`self-approval`, `pr-author-conflict`, or `actor-is-reviewer`), that login
is withheld from *all* of its motivations for this report, even ones that
would otherwise be clean. Explain this plainly, for example:

> "Alice would normally be asked to review for gates G3 and G6, but since
> she's a preparer on G9, none of her review requests are being suggested —
> not even for G3 and G6."

Translate the `withheld_cause.reason` on each `withheld-conflict` entry:

- `self-approval` — the resolved person is a preparer or the independent
  verifier for that gate; reviewing here would mean signing off on their own
  work.
- `pr-author-conflict` — the resolved login is the PR's own author.
- `actor-is-reviewer` — the resolved login is the verified `--as-bot`
  identity itself.

## Step 4 — Explain other refusal reason codes

Never show raw reason codes; translate any entries in `refusals` (and note
that these are separate from `withheld-conflict` — a refusal explains why a
`(gate, authority)` pair never became a candidate at all, not why an
already-built candidate was withheld):

- `authority-unknown` — that role has no entry in
  `.agentic-sdlc/authorities.json` yet; point back at
  `lifecycle-onboarding-github`'s Step 4.
- `authority-unassigned` — the role exists but has no one assigned; same
  pointer.
- `no-github-binding` — the assigned person's identity isn't in GitHub-login
  form; they need a GitHub identity binding set for that authority.
- `github-user-unresolved` — no GitHub account matches that login (also
  surfaced per-reviewer in Step 2 if the login did make it into the
  candidate list before failing this check).
- `not-a-collaborator` — the login is real but not a collaborator on this
  repository.
- `self-approval` / `pr-author-conflict` / `actor-is-reviewer` — see Step 3;
  these are the same independence reasons, reported here at the
  `(gate, authority)` level.
- `applicability-unknown` — the run record can't yet tell whether this
  authority applies to this gate.

A non-empty refusals list does not mean the whole report failed — report
exactly which logins/gates were clean, withheld, or unresolved; never
collapse this into a single pass/fail statement.

## Step 5 — Hand back a checklist, not an action

Close by restating plainly: nothing was requested on GitHub. If the human
wants to act on this, tell them to open the PR in the GitHub UI and request
reviews from the `to-request` (and, if they judge it worth a re-ping,
`review-stale`) logins themselves. Do not offer to do this for them beyond
what this skill's read-only report already covers.

## Throughout

- Never imply a review request was made — this command has no write path in
  this kernel version, full stop.
- Never fabricate a repo, PR number, login, gate id, or classification value.
- Never show raw JSON, YAML, or CLI flags to the human unless they explicitly
  ask to see the underlying files or commands.
- This report is advisory only — it is not gate-decision evidence and does
  not affect any gate's status. Point to `lifecycle-review-github` for
  actually recording a decision.
- Summarize outcomes in prose after running the report.
