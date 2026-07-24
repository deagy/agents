# New Service Workflow

This workflow covers work that proceeds beyond intake into design and delivery.
Use `product-intake.md` when the task only captures intent or baselines
requirements. Knowledge retrieval is required at every relevant phase under the
retrieval policy, but it is a cross-cutting prerequisite rather than G1-G10.

1. **Intent and requirements:** Product Intent Agent drafts the versioned intent; the Human Product Owner decides G1. Requirements Agent derives stable, traceable functional, non-functional, control, test, and evidence obligations; the Product Owner and Engineering Lead decide G2.
2. **Early assurance:** Governance Planner, Data Governance Engineer, and Cryptographic Assurance Engineer classify applicability, populate the SQS impact profile, and identify unresolved definitions. `unknown` applicable items fail closed.
3. **Architecture:** Cloud Architect maps the approved baseline and SQS profile to boundaries, APIs, data/trust flows, ADRs, failure/recovery behavior, and validation obligations. The Human System Architect decides G3.
4. **Governance and data:** Policy, jurisdiction, accreditation, classification, lineage, residency, non-egress, retention/deletion, and derived-output evidence are independently reviewed. The authorities in G4 decide progression.
5. **Security and crypto:** Threat Modeler and relevant identity, supply-chain, pipeline, and crypto specialists produce bounded attestations. Independent Security Reviewer and G5 human authorities decide progression.
6. **Implementation:** Frontend, backend, application, infrastructure, database, identity, policy, CI/CD, observability, and capacity roles implement in parallel within approved constraints. None may approve its own output.
7. **Verification:** Test Engineer, Black-Box Tester, End-User Tester, and independent code/infrastructure/pipeline/supply-chain reviewers verify the exact revision and artifacts. G6 requires requirements/control traceability and an independence declaration.
8. **Evidence:** Technical Writer updates approved documentation. Evidence Curator indexes, but does not manufacture or approve, source evidence and formally defined applicable BOMs. Compliance Reviewer and Release Owner decide G7.
9. **Release readiness and authorization:** Release Engineer assembles readiness evidence for G8. An Authorized Human Release Authority alone decides G9 for the exact artifact, target, identity, plan, window, rollback, and thresholds.
10. **Deployment and runtime:** Deploy progressively, verify, and follow `runtime-assurance.md` for G10 and feedback.

Failed gates return to the responsible artifact owner and name the earliest
required re-entry gate. A material change invalidates that gate and every
dependent downstream gate. A reviewer who makes a material correction becomes
an author and must transfer approval to a different independent reviewer.
