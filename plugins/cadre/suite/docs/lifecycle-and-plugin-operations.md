<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Lifecycle and plugin operations

This repository supplies the Secure Cloud role suite and provider profile. The
portable Agentic SDLC kernel, lifecycle schemas, gate transitions, and lifecycle
skills are maintained at [deagy/agentic-sdlc](https://github.com/deagy/agentic-sdlc)
— that ownership is permanent and applies to every consuming project,
including this one. This repository does not run its own `.agentic-sdlc/`
overlay; lifecycle schemas, run-record validators, and gate-authority logic
never move into this repo regardless.

## Conversational onboarding (recommended for non-engineers)

Anyone who would rather not run CLI commands or edit JSON/YAML directly should
ask an agent to run the `lifecycle-onboarding` skill
(`.agents/skills/lifecycle-onboarding/`). It drives the whole flow below —
choosing a profile, resolving human authorities, confirming commands, and
validating the result — through plain-language questions, for any project
(including this one). The rest of this document is the direct CLI reference,
kept for engineers who prefer it and for the skill's own implementation to
follow.

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
from other projects. Follow the [plugin README](../README.md)
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
