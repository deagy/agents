# Team Recipes

Three team compositions drawn from signals already present in this repo — not
invented groupings. Each names the roles, each teammate's distinct focus, and
how the lead synthesizes. See [runner-adapters.md](runner-adapters.md) for how
to actually spawn these on each runner, and what changes on Codex.

## Parallel review team

**Roles**: `code-reviewer` + `infrastructure-reviewer` +
`pipeline-security-reviewer` + `supply-chain-security-reviewer`.

**When**: a change touches multiple review-relevant surfaces at once
(application code, infrastructure, pipeline, dependencies). This is exactly
the group `agents/RUNBOOK.md`'s own implementation/review sequence already
lists together ("Code reviewer + Infrastructure reviewer + Pipeline security
reviewer + Supply chain security reviewer") — today dispatched as an ordinary
parallel wave; a team lets them challenge each other's findings before you see
the consolidated list.

**Each teammate's focus** (per their `AGENT.md`): `code-reviewer` —
correctness, security, maintainability, tests of the exact revision;
`infrastructure-reviewer` — IaC security, correctness, resilience, drift;
`pipeline-security-reviewer` — CI/CD trust boundaries, runner/token/artifact
controls; `supply-chain-security-reviewer` — dependency/SBOM/provenance/
signing/image risk.

**Synthesis**: the lead consolidates all four into one severity-ordered
findings list, same as an ordinary wave's "Consolidate Results" step — the
difference a team adds is teammates can flag interactions across each other's
domains first (for example, `pipeline-security-reviewer` noticing that an
infrastructure change `infrastructure-reviewer` approved actually widens CI
runner exposure).

**Downstream — do not fold into this team**: `security-reviewer` and
`compliance-reviewer` stay a *separate, sequential* step after this team's
findings synthesize. `RUNBOOK.md` documents this ordering explicitly
("Security reviewer -> Compliance reviewer"): compliance-reviewer's control
mapping depends on security-reviewer's consolidated risk assessment, so it
can't run as an independent peer in the same team.

**Gates**: G6–G8 (per `routing.yaml`'s `infrastructure` and `pipeline` routes).

## Cross-stack build team

**Roles**: `frontend-engineer` + `backend-engineer` +
`infrastructure-provisioner` + `cicd-engineer`.

**When**: `agents/orchestration/routing.yaml`'s `cross_stack` block already
detects this signal automatically — when 2 or more of the `frontend`,
`backend`, `infrastructure`, `pipeline` routes match the same task, it adds
`application-engineer` as support. That is this repo's own existing evidence
these four roles' work is independent and commonly concurrent —
`RUNBOOK.md`: "Implementation roles may work concurrently after architecture
and threat requirements are stable."

**Each teammate's focus**: build only their own layer — `frontend-engineer`
(React/TypeScript UI), `backend-engineer` (Go/PostgreSQL service),
`infrastructure-provisioner` (Terraform/Helm/Kubernetes),
`cicd-engineer` (pipeline for the new artifact). `application-engineer` is
consulted for cross-stack contract questions as support, not spawned as a
fifth teammate unless the task has substantial cross-stack glue code of its
own.

**Synthesis**: before spawning, the lead assigns each teammate a disjoint file
set — two teammates editing the same file causes silent overwrites, exactly
the failure mode Claude Code's own agent-teams guidance warns about. After
completion, hand the combined output to the parallel review team above.

**Gates**: varies by which routes matched (G3–G8).

## Competing-hypotheses debugging team

**Roles**: `debugging-engineer`, spawned 2–4 times — this is the one recipe
built on multiple instances of a *single* role pursuing different theories,
not multiple different roles.

**When**: `agents/workflows/debugging.md`'s root-cause loop hasn't converged
on one explanation from a single investigation, or the failure is
intermittent/environment-dependent enough that more than one theory is
plausible.

**Each teammate's focus**: one specific, named hypothesis assigned in the
spawn prompt (for example: "race condition in the connection pool," "stale
cache TTL," "upstream rate limiting") — naming them explicitly up front keeps
teammates from converging on the same theory.

**Synthesis**: unlike the other two recipes, this one is designed for active
mid-investigation challenge, not independent reporting — each teammate's job
includes trying to disprove the others' theories. The lead's role is to keep
that debate happening (prompt teammates to review each other's evidence)
rather than just collecting separate reports and picking one.

**Guardrail**: each teammate still operates under `debugging-engineer`'s
normal authority — reproduce, diagnose, apply the smallest safe fix; no
teammate may approve its own fix. Independent review is still required
afterward, per `debugging.md`.

**Gates**: none directly (debugging is typically pre-gate or gate-agnostic
root-cause work); the resulting fix still goes through the normal review
chain.

## On Codex CLI

None of the "synthesize via peer challenge" mechanics above are available —
see [runner-adapters.md](runner-adapters.md). Run the same role list as an
ordinary parallel wave on Codex, and perform the challenge/reconciliation step
yourself as the orchestrating session. For the debugging recipe specifically:
collect each spawned instance's hypothesis and evidence, then reason about
contradictions between them yourself before proposing a fix — Codex has no
way to let the instances do that directly.
