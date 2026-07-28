# Terminology

| Term | Meaning |
| --- | --- |
| Agent definition | The canonical `AGENT.md` describing one role's purpose, inputs, authority, escalation conditions, and completion criteria. |
| Catalog | `agents/catalog.yaml`, the machine-readable inventory of role IDs, definition paths, and phases. |
| Provider | A package that supplies roles, profiles, and extensions to the portable Agentic SDLC kernel. |
| Provider repository | A distribution project that supplies provider resources and dispatch inputs to other consuming projects. Being a provider is orthogonal to being a lifecycle consumer: a provider repository may (this one does) also run its own `.agentic-sdlc/` overlay and run records to track its own roadmap, without that overlay carrying any authority over another project's gates. |
| Profile | A selectable lifecycle configuration that combines a kernel baseline with project-relevant roles and defaults. |
| Workflow | A documented sequence for a class of work, such as a new service, debugging, release, or incident. |
| Dispatch plan | A reviewable selector output identifying roles, reviewers, workflow, gates, evidence, and handoffs. |
| Run record | The project-owned record of lifecycle state, decisions, evidence, approvals, and invalidations. |
| Quality gate | A lifecycle checkpoint requiring defined criteria and evidence before progression. |
| Human gate | A decision reserved for an accountable human, such as risk acceptance, policy exception, production authorization, or release approval. |
| Independent reviewer | A role that evaluates an exact revision separately from its author and cannot approve its own work. |
| Generated artifact | A runner or package file produced from canonical source; it is regenerated rather than edited by hand. |
| Platform | An external organization/platform whose impact-category and BOM (SBOM/CBOM/QBOM/AI-BOM/Trust-BOM/Time-BOM) semantics this repository deliberately does not define — see `agents/shared/platform-impact-profile.yaml`. A consuming project must supply its own authorized definitions and owners before treating any category as applicable; `unknown` blocks the relevant gates by design, not by omission. |

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

The kernel owns lifecycle state and gate transitions, permanently — no
provider ever takes over schema, validator, or gate-authority ownership. This
repository owns the Secure Cloud provider content, and also runs its own
`.agentic-sdlc/` overlay as an ordinary consumer for its own roadmap. Every
consuming target project, including this one, owns only its own overlay and
run records; none carries authority over another's. A provider or agent
cannot grant itself human authority.
