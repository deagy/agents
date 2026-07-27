# Agent Catalog

Reviewed catalog of the repository's 39 agents. Every catalog entry has a corresponding `AGENT.md` definition.

| Agent | Phase | Description |
|---|---|---|
| Product Intent Agent | Planning | Converts human-defined objectives into versioned, reviewable product intent. |
| Requirements Agent | Planning | Decomposes intent into stable, testable, traceable requirements and obligations. |
| Governance Planner | Design | Identifies jurisdiction, accreditation, policy, control, and evidence obligations. |
| Data Governance Engineer | Design | Defines data classification, lineage, residency, retention, deletion, and derived-output requirements. |
| Cryptographic Assurance Engineer | Security | Assesses algorithms, keys, certificates, cryptographic agility, and downgrade resistance. |
| Cloud Architect | Design | Designs secure, resilient, operable, and cost-aware system architectures. |
| Threat Modeler | Design | Identifies threats and translates them into prioritized, testable mitigations. |
| API Contract Engineer | Design | Defines API and schema shapes, versioning, compatibility, pagination, and error semantics. |
| Application Engineer | Build | Implements approved cross-stack application capabilities and tests. |
| Frontend Engineer | Build | Builds secure, accessible browser-facing application code and API integrations. |
| Backend Engineer | Build | Implements secure backend services, data changes, migrations, and tests. |
| Infrastructure Provisioner | Build | Creates reusable infrastructure and deployment configuration for review. |
| CI/CD Engineer | Build | Builds secure pipelines for testing, scanning, artifacts, promotion, deployment, and rollback. |
| Debugging Engineer | Build | Reproduces and diagnoses code, configuration, runtime, test, and agent-system failures. |
| Test Engineer | Verify | Designs and executes risk-based tests across application, infrastructure, pipeline, resilience, and security behavior. |
| Black-Box Tester | Verify | Tests externally visible behavior without relying on implementation internals. |
| End-User Tester | Verify | Evaluates user workflows, usability, accessibility, and user readiness. |
| Performance & Load Testing Engineer | Verify | Measures throughput, latency, resource use, and capacity against stated targets. |
| Chaos & Resilience Engineer | Verify | Runs controlled fault-injection exercises to validate recovery, RTO/RPO, and alerting. |
| Support Triage Agent | Support | Classifies, sanitizes, reproduces, and routes inbound support issues. |
| Escalation Manager | Support | Routes urgent, ambiguous, high-risk, or authority-blocked work to the correct owner. |
| Incident Commander | Support | Coordinates major-incident response, timelines, mitigations, communications, and follow-up. |
| Observability SRE | Operations | Designs telemetry, SLOs, alerts, dashboards, and runtime operational readiness. |
| Cost & Capacity Planner | Planning | Estimates demand, headroom, storage growth, utilization, and cost tradeoffs. |
| FinOps Engineer | Operations | Monitors actual spend, utilization, quotas, anomalies, and sizing drift. |
| Secrets & Identity Engineer | Security | Designs secret handling, workload identity, credential lifecycle, and authorization boundaries. |
| Policy-as-Code Engineer | Security | Designs machine-enforced infrastructure, deployment, delivery, and repository guardrails. |
| Database Reliability Engineer | Operations | Reviews migration safety, backup/restore, schema lifecycle, performance, and database reliability. |
| Release Engineer | Release | Coordinates controlled promotion of approved artifacts with evidence and rollback readiness. |
| Code Reviewer | Review | Independently reviews code for correctness, security, maintainability, and test adequacy. |
| Accessibility Reviewer | Review | Independently verifies browser-facing changes against accessibility targets. |
| Infrastructure Reviewer | Review | Reviews infrastructure-as-code for security, correctness, resilience, and unintended impact. |
| Pipeline Security Reviewer | Review | Reviews CI/CD trust boundaries, artifact integrity, and release-control integrity. |
| Supply Chain Security Reviewer | Review | Reviews dependency, package, container, IaC provider, SBOM, provenance, and signing risks. |
| Security Reviewer | Review | Independently assesses end-to-end security, cryptographic risk, controls, and residual risk. |
| Compliance Reviewer | Review | Verifies applicable controls and durable, audit-ready evidence. |
| Technical Writer | Documentation | Produces accurate task-oriented documentation from approved technical sources. |
| Evidence Curator | Evidence | Collects, indexes, protects, and preserves delivery and compliance evidence. |
| Knowledge Store Steward | Knowledge | Operates the vectorized knowledge store, including ingestion, provenance, retrieval quality, and retention. |

Sources: [`agents/agents/catalog.yaml`](agents/agents/catalog.yaml) and the corresponding `AGENT.md` definitions under [`agents/agents`](agents/agents).
