---
name: version-control-workflow
description: Perform git branching, merge and rebase, history repair, conflict resolution, and pull/merge request hygiene on GitLab or GitHub. Use when a change needs history rewritten, a bad commit undone, a conflict resolved, a branch or tag convention chosen, or a PR/MR prepared for review.
---

> Packaged suite note: when the current project has no local `roster/` tree, resolve suite files under `../../suite/roster/` relative to this `SKILL.md`. The packaged plugin is self-contained; do not look for the source checkout.


# Version Control Workflow

Procedural know-how for operating git and its two supported forges. This is a
skill, not a role: it carries no authority of its own and does not approve,
merge, release, or bypass a review. The role that owns the change owns the
result of running these procedures.

Not to be confused with the `agent-version-control` role, which tracks
provenance of this suite's *role definitions* and has nothing to do with git.

## Before rewriting anything

History rewriting is destructive and, once pushed, destructive for everyone
else too. Establish all three before starting:

1. **Is the branch shared?** A rewrite of a branch someone else has checked out
   forces them to recover manually. Rewrite only your own unmerged work unless
   the humans sharing it have agreed.
2. **Is it protected?** Protected refs reject force-pushes by design. Wanting
   the rewrite is not grounds for lifting the protection — that is a human
   decision, and lifting it silently defeats the control.
3. **Where is the recovery point?** Record the pre-rewrite SHA (`git rev-parse
   HEAD`) or tag it. `git reflog` expires; a written-down SHA does not.

Prefer `--force-with-lease` over `--force`. Plain `--force` overwrites a remote
that moved since you last fetched, discarding whatever arrived in between
without telling you.

## Merge or rebase

Both are correct in different places; the choice is about what the history is
for, not about preference.

| Situation | Use |
| --- | --- |
| Bringing a shared branch up to date | merge — a rebase rewrites commits others hold |
| Tidying your own unpushed work before review | rebase, or `rebase -i` to squash |
| Integrating a reviewed branch into the default branch | whichever the project already uses; do not switch conventions mid-stream |
| Recovering a branch that has drifted far behind | merge first, resolve once, rather than resolving the same conflict at every rebased commit |

`git rerere` records a conflict resolution once and replays it, which is what
makes a long rebase tolerable. Turn it on before a large one, not during.

## Undoing

- **Pushed, shared** → `git revert`. It adds a commit rather than removing one, so nobody else has to recover.
- **Local, not pushed** → `git reset` (`--soft` keeps the changes staged, `--hard` discards them; `--hard` is the one that loses work).
- **A commit lost by a reset or rebase** → `git reflog` still has it for its expiry window; `git cherry-pick` it back.
- **A secret committed** → reverting is not enough. The blob remains reachable in history and in every clone and fork. Treat the secret as disclosed, rotate it first, and only then decide whether rewriting history is worth the disruption. Rotation is the control; rewriting is cleanup.

## Conflicts

Resolve for intent, not for syntax. A conflict resolved so the file merely
parses is the failure mode worth guarding against, because it passes review by
looking plausible.

1. `git status` to see the full conflicted set before editing any of it — resolving file by file hides conflicts that only make sense together.
2. `git log --merge -p <file>` shows the commits on both sides that touched it.
3. After resolving, run the tests that cover both sides. A clean merge is not evidence of a correct one.
4. `git checkout --conflict=diff3 <file>` shows the common ancestor as well as both sides, which is usually what makes an ambiguous conflict decidable.

## Branch and tag conventions

- Name branches for the change, not the person — `feat/role-expansion`, not `daniel-work`.
- Tags that carry a release must be immutable. Moving a tag after publication breaks anyone who pinned it and silently changes what a checksum refers to.
- In a monorepo publishing more than one component, prefix tags per component (`plugin-v*`, `kernel-v*`). An unprefixed `v<version>` scheme collides across components, and the collision fails *silently* — an already-tagged check reports "nothing to do".
- Sign tags where the project requires it, and verify the signature after pushing. A forge matches a signing key to the signer's account **by email**, so a tag made under a bot identity can carry a cryptographically valid signature and still show as unverified.

## Pull and merge requests

The two forges differ in ways that matter to review integrity; do not carry a
control's name across from one to the other.

| Concern | GitLab | GitHub |
| --- | --- | --- |
| Change unit | merge request | pull request |
| Required review | approval rules | required reviews / rulesets |
| Ref protection | protected branches | branch protection or rulesets |
| CI identity | job token, protected variables | `GITHUB_TOKEN` permissions, OIDC federation |
| Environment approval | protected environments | environment reviewers |

Regardless of forge: keep a request scoped to one reviewable change, write the
description for someone who was not in the conversation, and never approve your
own work — that separation is a hard invariant of this suite, not a convention.

## Escalate rather than proceed

Stop and hand to a human when a rewrite would touch a protected or shared ref,
when a secret has reached history, when resolving a conflict requires deciding
which side's behavior is correct and the answer is not in the change's own
acceptance criteria, or when the operation would drop commits nobody has agreed
to lose.
