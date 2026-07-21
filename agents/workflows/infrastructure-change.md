# Infrastructure Change Workflow

1. Classify scope, environment, affected data, blast radius, architecture impact, and required approvals.
2. If architecture or trust boundaries change, require cloud architect and threat modeler review before implementation.
3. Infrastructure provisioner updates IaC and produces validation evidence plus a plan tied to the exact revision and target.
4. Infrastructure reviewer independently evaluates code and plan, explicitly covering create/update/replace/delete, IAM, exposure, encryption, logging, backup, data, state, cost, and rollback effects.
5. Security and compliance reviewers participate when the change affects scoped controls, sensitive data, identity, keys, public exposure, logging, or recovery.
6. Release engineer verifies the reviewed plan still matches the approved revision and target, then obtains required human approval.
7. A scoped deployment identity applies the reviewed plan. Do not re-plan silently during production apply.
8. Verify health, security telemetry, drift, policy state, and expected resources. Roll back or escalate on threshold failure.

Always stop for unexpected deletion/replacement, privilege expansion, public exposure, state manipulation, key changes, data migration, or target ambiguity.
