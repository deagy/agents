# Terminology

| Term | Meaning |
| --- | --- |
| Agent definition | The canonical `AGENT.md` describing one role's purpose, inputs, authority, escalation conditions, and completion criteria. |
| Catalog | `agents/catalog.yaml`, the machine-readable inventory of role IDs, definition paths, and phases. |
| Provider | A package that supplies roles, profiles, and extensions to the portable Agentic SDLC kernel. |
| Profile | A selectable lifecycle configuration that combines a kernel baseline with project-relevant roles and defaults. |
| Workflow | A documented sequence for a class of work, such as a new service, debugging, release, or incident. |
| Dispatch plan | A reviewable selector output identifying roles, reviewers, workflow, gates, evidence, and handoffs. |
| Run record | The project-owned record of lifecycle state, decisions, evidence, approvals, and invalidations. |
| Quality gate | A lifecycle checkpoint requiring defined criteria and evidence before progression. |
| Human gate | A decision reserved for an accountable human, such as risk acceptance, policy exception, production authorization, or release approval. |
| Independent reviewer | A role that evaluates an exact revision separately from its author and cannot approve its own work. |
| Generated artifact | A runner or package file produced from canonical source; it is regenerated rather than edited by hand. |

## Relationship between the two repositories

```text
portable Agentic SDLC kernel
    └── target-project overlay and run records

Secure Cloud provider
    ├── role catalog and AGENT.md definitions
    ├── shared policies and workflows
    ├── knowledge-store procedures
    └── runner/plugin packaging
```

The kernel owns lifecycle state and gate transitions. This repository owns the
Secure Cloud provider content. A provider or agent cannot grant itself human
authority.
