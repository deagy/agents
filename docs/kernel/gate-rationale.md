# Why Ten Gates? — Rationale for the G1–G10 Lifecycle Sequence

This document explains the rationale behind the specific ten gates (G1–G10) in the Agentic SDLC lifecycle, why this number was chosen over eight or twelve, and the historical context for each gate.

## Design Principles

The gate sequence was designed around three constraints:

1. **Separation of duties**: No single agent or automation may approve its own work. Each gate requires an independent authority.
2. **Progressive disclosure**: Gates should only require information that is actually available at that point in the lifecycle.
3. **Bounded authority**: Each gate has a specific, limited scope of approval — no gate is a catch-all.

## Why Not Eight Gates?

A simplified eight-gate model would merge or eliminate:

- **G1 (Intent) + G2 (Requirements)**: These serve different purposes. G1 captures the *why* (intent, source, constraints) while G2 captures the *what* (detailed requirements, acceptance criteria). Merging them loses the ability to reject a task at the intent stage before investing effort in detailed requirements.
- **G6 (Design Review) + G7 (Implementation Approval)**: Design approval and implementation approval serve different authority functions. An agent could have authority over one without the other.
- **G9 (Release Approval) + G10 (Post-Release Review)**: Release approval is forward-looking (is this ready to ship?); post-release review is backward-looking (did it work as intended?). They answer different questions and require different evidence.

Eight gates would create authority overlaps where a single reviewer would need expertise across too many domains, weakening the separation-of-duties guarantee.

## Why Not Twelve Gates?

A twelve-gate model would add:

- **G11 (Security Testing Gate)**: Security testing is already covered by G5 (Implementation) where security-reviewer roles are dispatched. Adding a separate gate would create redundancy without additional authority separation.
- **G12 (Performance Testing Gate)**: Similarly, performance testing is part of G5's testing authority. A separate gate would be a checkpoint without new decision authority.
- **G0 (Pre-Intent)**: Pre-intent activities (exploration, spike tasks) are handled by the `needs-triage` fallback in role selection, not by a lifecycle gate. Lifecycle gates are for committed work.

Twelve gates would create administrative overhead without meaningful authority separation.

## The Ten Gates Explained

### G1 — Intent (Why are we doing this?)

**Purpose**: Capture the source of the work, its justification, and high-level constraints before any effort is invested.

**Why first**: Every piece of work needs a source. Without a documented intent, there is no basis for approval. This gate prevents "shadow projects" where work begins without a recorded purpose.

**Authority**: The intent source (e.g., a stakeholder, a business case, a regulatory requirement) is the approving authority. The agent preparing the gate cannot be the same identity as the source.

**Evidence**: Source document, business case, or regulatory reference.

### G2 — Requirements Baseline (What exactly are we building?)

**Purpose**: Define detailed requirements, acceptance criteria, and scope boundaries.

**Why separate from G1**: G1 says "we need a payment system"; G2 says "the payment system must support X, Y, Z with these specific acceptance criteria." The transition from intent to requirements is significant enough to warrant separate authority.

**Authority**: Requirements-agent roles with domain expertise in the relevant area.

**Evidence**: Requirements document, acceptance criteria, scope boundary definition.

### G3 — Architecture Design (How will we build it?)

**Purpose**: Approve the architectural approach before implementation begins.

**Why third**: Design must come before code. An architecture gate prevents costly rework where implementation has to be redone because the design was wrong.

**Authority**: Architecture-authority roles with system design expertise.

**Evidence**: Architecture document, design decisions, technology choices.

### G4 — Security Review (Is it secure?)

**Purpose**: Independent security assessment of the design and implementation approach.

**Why fourth**: Security review should happen early (after design) but before implementation is complete. This allows security concerns to be addressed during development, not after.

**Authority**: Security-reviewer roles. Must be independent of the design authority.

**Evidence**: Security assessment, threat model, vulnerability analysis.

### G5 — Implementation Approval (Is the code ready?)

**Purpose**: Approve the implementation for quality, test coverage, and requirements compliance.

**Why fifth**: This is the main "go/no-go" for code. Implementation approval requires that G1-G4 are all satisfied and that the code meets the requirements defined in G2.

**Authority**: Code-reviewer, test-engineer, and engineering-lead-aide roles.

**Evidence**: Code review results, test results, requirements traceability matrix.

### G6 — Integration Testing (Does it work together?)

**Purpose**: Verify that components work together in an integrated environment.

**Why sixth**: Integration testing requires all components to be individually approved (G5) before they can be tested together. This gate catches interface mismatches that unit testing misses.

**Authority**: Integration-test-engineer or equivalent roles.

**Evidence**: Integration test results, interface compliance reports.

### G7 — User Acceptance (Does it meet the user's needs?)

**Purpose**: Validate that the implemented system meets the end-user requirements.

**Why seventh**: UAT comes after technical validation (G5, G6) because users don't need to see broken or untested code. This gate ensures the system solves the problem defined in G2.

**Authority**: End-user-tester or product-owner-aide roles representing the stakeholder.

**Evidence**: UAT test results, user feedback, acceptance criteria sign-off.

### G8 — Performance & Resilience (Will it handle real load?)

**Purpose**: Verify performance under expected and stress conditions.

**Why eighth**: Performance testing requires a fully integrated, UAT-approved system. Testing performance on incomplete systems gives misleading results.

**Authority**: Performance-testing-engineer and chaos-resilience-engineer roles.

**Evidence**: Performance test results, load testing reports, resilience test results.

### G9 — Release Approval (Is it ready to ship?)

**Purpose**: Final go/no-go decision for production deployment.

**Why ninth**: Release approval is the last gate before the system changes production state. It requires confirmation that all previous gates are satisfied and that the deployment plan is sound.

**Authority**: Release-engineer and release-owner-aide roles. Must include a human approver.

**Evidence**: Release plan, deployment checklist, rollback plan, all previous gate approvals.

### G10 — Post-Release Review (Did it work as intended?)

**Purpose**: Evaluate the release against its original intent and requirements.

**Why tenth (and last)**: Post-release review closes the loop. It compares actual outcomes against the intent documented in G1 and the requirements from G2. This evidence feeds back into future G1 decisions.

**Authority**: Evidence-curator and governance-planner roles.

**Evidence**: Post-release metrics, incident reports, user feedback, comparison against G1/G2 baseline.

## Gate Dependencies

```
G1 (Intent) → G2 (Requirements) → G3 (Architecture)
                                    │
                                    ▼
                               G4 (Security)
                                    │
                                    ▼
                               G5 (Implementation) → G6 (Integration)
                                                        │
                                                        ▼
                                                   G7 (UAT)
                                                        │
                                                        ▼
                                                 G8 (Performance)
                                                        │
                                                        ▼
                                                   G9 (Release)
                                                        │
                                                        ▼
                                                   G10 (Post-Release)
```

G4 can run in parallel with G3 (security review of design can begin as soon as architecture is drafted). G6 requires G5 completion. G7 requires G6 completion. The chain G5 → G6 → G7 → G8 → G9 is strictly sequential because each gate depends on evidence from the previous one.

## Invalidation and Re-entry

When a gate is invalidated (e.g., new security vulnerability discovered after G4), the system re-baselines from the earliest affected gate. This is documented in `reentry.py` and the `invalidate`/`reenter` CLI commands. The invalidation flow ensures that:

1. The invalidation is recorded with evidence
2. All downstream gates are marked as pending re-approval
3. The specific artifacts that need regeneration are identified

## Impact Categories

The `impact_categories` mechanism in gate contracts is reserved for future compliance framework adapters (SOC2, ISO27001, NIST, FedRAMP). When implemented, each gate will be mapped to relevant framework controls, enabling automated compliance reporting.

## Historical Context

The ten-gate model evolved from early discussions about what minimal governance looks like for autonomous agent systems. The key insight was that **authority separation** — not gate count — is what makes governance effective. Ten gates provide enough separation to be meaningful without creating so much overhead that teams bypass the process.

The model was validated against three scenarios:
1. **Small feature task** (2-3 days): G1, G2, G3, G5, G9 — skips integration/performance gates
2. **Medium system change** (2-4 weeks): G1-G8, G9, G10 — full sequence
3. **Critical infrastructure change**: All gates with enhanced human approval at G9

## See Also

- [Agentic SDLC README](../README.md) — full system documentation
- [CLAUDE.md](../CLAUDE.md) — architecture notes
- [AGENTS.md](../AGENTS.md) — repository rules and safety guidelines
