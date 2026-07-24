<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Rollback Workflow

1. Declare the trigger, incident/change identifier, decision owner, affected environment, and current blast radius.
2. Preserve logs, events, artifact identifiers, plans, and relevant state before changing the system when safe.
3. Release engineer selects the pre-approved rollback or roll-forward procedure; obtain emergency authorization required by policy.
4. Use the scoped deployment identity and immutable known-good artifacts. Do not improvise source changes inside the release process.
5. Account for database/schema compatibility, irreversible data changes, queued work, caches, DNS, keys, and infrastructure state.
6. Verify service health, security signals, data integrity, and customer impact after recovery.
7. Evidence curator records the timeline and artifacts; reviewers identify follow-up findings without delaying urgent containment.

Escalate to incident response when compromise, data loss/exposure, state corruption, or safe recovery uncertainty is suspected.
