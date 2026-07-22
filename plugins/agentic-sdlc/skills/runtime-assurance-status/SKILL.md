---
name: runtime-assurance-status
description: Assess Agentic SDLC runtime conformance for a deployed service and route observed drift, SLO, security, data, governance, incident, or user-impact findings into controlled feedback. Use for G10 observation windows, deployed-version status, post-release assurance, or runtime findings that require traced remediation.
---

# Runtime Assurance Status

1. Read repository instructions, `.agentic-sdlc/`, the run record, approved release bindings, runtime-assurance workflow, and available observation evidence.
2. Locate `../../scripts/agentic_sdlc.py`, run `status --help`, then retrieve status for the exact task and deployment using supported flags.
3. Verify deployed version/configuration/environment identity and observation window before interpreting SLO, business, security, data, trust, governance, drift, incident, and support signals.
4. Coordinate observability evidence and request independent security, governance, support, incident, or debugging participation when their domains are implicated. Do not create a generic runtime approver.
5. Fail closed when deployment identity, evidence provenance, applicable signal coverage, or required authority is unknown. An agent may prepare G10 evidence but cannot approve conformance for the Human Service Owner or implicated Security/Governance Leads.
6. Keep G10 quality assessment separate from `human_gates`. A rollback, production change, destructive remediation, persistent migration, or privileged identity action requires its own explicit authorization.
7. Report conformance, observation coverage, findings, owners, incidents, and feedback routing. Route material findings to rollback/incident response or re-entry at G1, G2, or G6 as appropriate; record invalidation before relying on stale gates.
