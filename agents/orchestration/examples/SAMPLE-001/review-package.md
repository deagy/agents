# Document Upload Example Review Package

## Requested disposition

Review the proposed design for readiness to begin implementation. Do not treat this package as authorization to apply infrastructure, run persistent migrations, merge, or release.

## Reviewer inputs

- `architecture.md`
- `data-flow.md`
- `state-machines.md`
- `api-contract.md`
- `data-model.md`
- `decision-register.yaml`
- `risk-register.md`
- `acceptance-criteria.md`
- `adrs/*.md`
- `design-resolution-plan.json`
- companion orchestration report

## Required review sequence

1. Human decision owners populate and approve or reject every blocking decision.
2. Cloud architect verifies topology, contracts, alternatives, and decision coherence.
3. Threat modeler re-evaluates assets, boundaries, high threats, mitigations, and verification tasks.
4. Infrastructure reviewer verifies chosen provider/state, Proxmox/Talos/Kubernetes controls, PostgreSQL/object durability, plan evidence requirements, and rollback.
5. Pipeline-security reviewer verifies runner trust, tokens, protected environments, pinning, provenance/signing, registry, and admission.
6. Security reviewer consolidates residual risk and issues the implementation-gate disposition.
7. Compliance reviewer participates when classification/framework scope is known.

## Required outputs

- Completed `orchestration/review-response-template.md` per reviewer.
- Findings conforming to `shared/output-schemas/finding.schema.json`.
- Exact package revision and exclusions.
- Knowledge-store retrieval status and citations actually used.
- Explicit `approve`, `request-changes`, `needs-information`, or `blocked` decision.

## Automatic re-selection example

Resolve `$AgentPython` with the Python 3.10+ probe in `agents/RUNBOOK.md` first.

```powershell
Set-Location agents/orchestration
& $AgentPython.Path @($AgentPython.Args) -B src/select_agents.py `
  --task "Review resolved document-upload architecture for implementation readiness" `
  --files "<example-package>/architecture.md,<example-package>/decision-register.yaml" `
  --task-id EXAMPLE-REVIEW `
  --classification internal
```

## Gate outcome rule

Implementation remains blocked if any blocking decision is unassigned/unapproved, a critical/high finding is unresolved, required evidence is unavailable, or infrastructure/security review remains blocking. Risk acceptance and exceptions require authorized human owners.
