# Support Escalation Workflow

1. **Dispatcher:** Retrieve authorized support, incident, and role-specific context. Record unavailable, empty, unauthorized, or conflicting knowledge.
2. **Support triage agent:** Sanitize the report, classify severity, confirm scope, preserve evidence, and select the next specialist. Provide only user-safe updates.
3. **Black-box tester:** Reproduce the issue through externally available surfaces and capture observable evidence.
4. **End-user tester:** Validate affected personas, critical journeys, accessibility, and support-message clarity when user experience is in scope.
5. **Specialist implementation or review agents:** Frontend, backend, infrastructure, CI/CD, documentation, security, compliance, evidence, or release roles investigate only the scoped artifact or target.
6. **Escalation manager:** Coordinate unresolved, critical/high, ambiguous, customer-visible, or human-requested cases.
7. **Human escalation:** An accountable human decides on production action, risk acceptance, customer communication, destructive remediation, incident declaration, or policy exception.
8. **Closure:** Support triage records the outcome, evidence, owner, user-safe resolution, follow-up work, and knowledge-store proposal when appropriate.

Stop when required authority, target identity, blast radius, rollback, or evidence is ambiguous. A support or escalation agent may coordinate and recommend, but cannot approve its own closure for critical/high issues.
