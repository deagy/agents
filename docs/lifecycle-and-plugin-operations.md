# Lifecycle and plugin operations

This repository supplies the Secure Cloud role suite and provider profile. The
portable Agentic SDLC kernel, lifecycle schemas, gate transitions, and lifecycle
skills are maintained at [deagy/agentic-sdlc](https://github.com/deagy/agentic-sdlc)
— that ownership is permanent and applies to every consuming project,
including this one. This checkout also runs its own `.agentic-sdlc/` overlay
and run records (see "This repository's own lifecycle overlay" below) to track
its own catalog/plugin roadmap; that overlay carries no authority over any
other project's gates, and it does not change the rule that lifecycle schemas,
run-record validators, or gate-authority logic never move into this repo.

## Conversational onboarding (recommended for non-engineers)

Anyone who would rather not run CLI commands or edit JSON/YAML directly should
ask an agent to run the `lifecycle-onboarding` skill
(`.agents/skills/lifecycle-onboarding/`). It drives the whole flow below —
choosing a profile, resolving human authorities, confirming commands, and
validating the result — through plain-language questions, for any project
(including this one). The rest of this document is the direct CLI reference,
kept for engineers who prefer it and for the skill's own implementation to
follow.

## This repository's own lifecycle overlay

This repository's `.agentic-sdlc/` overlay uses `--profile generic` (not
`secure-cloud` — this repo is the *source* of the secure-cloud roles, not a
consumer of them) and no runner (`--runner` is intentionally omitted): a
`--runner claude`/`--runner both` init would write `.claude/agents/*.md` or
`.codex/agents/*.toml` subagent wrapper files into this checkout, which
`test_repository_health.py`'s
`test_repository_profile_and_local_override_policy_stay_current` forbids,
since this repo is the source those wrappers are generated *from*, not a
place that holds project-local copies of them. As a single-maintainer
repository, all 8 required human authority roles (Product Owner, Engineering
Lead, System Architect, Governance Lead, Security Lead, Release Owner, Release
Authority, Service Owner) resolve to the same maintainer — this is valid: the
kernel's author/reviewer separation check applies to Secure Cloud agent roles
assigned to a route, not to human authority-role holders. The 5 conditional
roles (Data/Control Owner, Human Key Owner, UAT Product Owner, and the two
runtime-implicated Security/Governance Lead roles) are marked
`not-applicable` with a rationale, since this repository holds no persistent
data-subject records or key material of its own, has no separate
user-acceptance-testing environment, and is not itself a deployed,
runtime-implicated service. Authority `assignee` values use the kernel's
`github.com/<login>`-prefixed identity format rather than a name or email
address, since this repository is public. Run `./bin/cadre sdlc validate
--root .` to confirm the overlay stays clean; CI runs the same check.

`.agentic-sdlc/project.json`'s `detected.root` is intentionally hand-set to
`"."` rather than the absolute local path `agentic-sdlc init`/`detect`
normally writes there (`detect_repository()` always resolves and writes an
absolute path, which would leak the initializing machine's directory layout
and OS username into this public repo's history). This field is write-only
metadata — nothing in the kernel reads it back for path resolution or
validation — but re-running `init`/`detect` against this repo would silently
regenerate the absolute path, so don't do that without re-applying this
override.

## Initialize a target project (direct CLI)

Install the reviewed standalone release and make its executable available as
`agentic-sdlc` or through `AGENTIC_SDLC_BIN`:

```sh
git clone https://github.com/deagy/agentic-sdlc.git
git -C agentic-sdlc checkout v0.3.0
export AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc
cadre sdlc init --root /path/to/target --profile secure-cloud
```

The target project owns its `.agentic-sdlc/` records and consequential
decisions. Initialization detects candidate technology values but does not
assign human authorities, accept risk, decide compliance applicability, or
authorize persistent or production environments.

Projects using a different technology stack should use the standalone kernel's
appropriate generic profile rather than importing Secure Cloud-specific roles.

## Install the suite globally

The self-contained plugin makes this repository's roles and skills available
from other projects. Follow the [plugin README](../plugins/cadre/README.md)
for runner-specific installation and regeneration details. Prefer a
project-local lifecycle profile when only one project needs the Secure Cloud
roles.

## GitHub-backed human approvals

When configured by the target project, an approved GitHub pull-request review
can be the authoritative source for a human gate decision:

```sh
cadre sdlc approve-from-github-pr \
  --root /path/to/target --task-id TASK-42 --gate G2 \
  --role product_owner --repo OWNER/REPO --pr 42 \
  --commit-sha "$GITHUB_SHA"
```

This requires authenticated GitHub CLI access and fails closed when the
repository, review, authority, or revision binding does not match. Validate the
run record afterward. A valid approval advances to the next applicable gate
only when the lifecycle criteria and authority checks pass.

## Upgrade and regenerate

Pin the standalone kernel and provider versions in automation. When canonical
roles, skills, or provider metadata change, regenerate the packaged plugin
from source and inspect the complete generated diff. Generated output is a
distribution artifact; it does not become a new source of authority.

For detailed lifecycle commands and evidence rules, use the standalone
project's documentation and the repository [runbook](../agents/RUNBOOK.md).
