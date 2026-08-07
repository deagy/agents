# ADR 0005: Kubernetes Workload Isolation

- Status: Proposed — platform capabilities required
- Owners: Platform and security

## Context

The BFF, API, scanner, and promotion worker have different trust and credential requirements. Shared identities or unrestricted networking would undermine containment.

## Decision

Deploy in a dedicated namespace using distinct service accounts, namespace-scoped RBAC, default-deny ingress/egress, explicit flows, restricted pod security, non-root/read-only containers, dropped capabilities, seccomp, resource/ephemeral-storage limits, probes, disruption controls, quotas, and topology spread.

Expose only the same-origin ingress/BFF. Keep the API, PostgreSQL, scanner, promotion worker, and object stores private. Use an approved external secret mechanism and short-lived workload identity where supported.

## Consequences

- CNI, policy engine, ingress, secret mechanism, and observability integrations must support these controls.
- Scanner isolation may require a stronger runtime/sandbox based on supported file formats.

## Approval criteria

Approve cluster/namespace, CNI/policy enforcement, ingress/TLS/DNS, exact network flows, service-account/RBAC matrix, secret mechanism, scanner sandbox, quotas, capacity, and Talos/Proxmox failure-domain placement.
