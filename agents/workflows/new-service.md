# New Service Workflow

1. **Dispatcher:** Retrieve authorized role-specific context for the task, attach cited bundles, and record empty, unavailable, or blocked retrievals.
2. **Cloud architect:** Convert requirements, data classification, availability and recovery targets, constraints, and cited relevant history into an architecture proposal and ADRs.
3. **Threat modeler:** Map assets, actors, trust boundaries, abuse paths, mitigations, and residual risks.
4. **Frontend engineer, backend engineer, application engineer when cross-stack coordination is needed, and infrastructure provisioner:** Implement in parallel within the approved design; none may approve its own output.
5. **CI/CD engineer:** Implement least-privilege build, scan, artifact, promotion, deployment, verification, and rollback automation.
6. **Test engineer, black-box tester, and end-user tester when applicable:** Execute functional, negative, externally observable, user-journey, accessibility, resilience, security, and recovery tests appropriate to risk.
7. **Support triage agent:** Review user-impacting defects, supportability gaps, safe evidence handling, and owner routing.
8. **Independent reviewers:** Code reviewer, infrastructure reviewer, and pipeline security reviewer inspect exact revisions and artifacts.
9. **Security and compliance reviewers:** Consolidate residual risk and control evidence. Route exceptions to accountable humans.
10. **Technical writer and evidence curator:** Finalize operational documentation and a preserved snapshot/run evidence index with integrity hashes.
11. **Escalation manager and release engineer:** Coordinate blocked gates or human-only decisions, then verify gates, coordinate explicit human production approval, release progressively, validate, and record the result.

Return to the owning implementation role whenever a gate fails. A reviewer who makes a material fix must transfer approval to another independent reviewer.
