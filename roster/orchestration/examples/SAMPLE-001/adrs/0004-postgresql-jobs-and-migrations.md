# ADR 0004: PostgreSQL Metadata, Jobs, and Compatible Migrations

- Status: Proposed — topology and recovery objectives required
- Owners: Backend/database and service owners

## Context

The service needs authoritative metadata, idempotency, session/audit state, and durable scan/promotion work without introducing an unselected queue product.

## Decision

Use PostgreSQL with pgx v5 for document metadata, sessions, idempotency bindings, audit/outbox records, and leased scan/promotion jobs. Keep binary documents in object storage. Use bounded pools, deadlines, parameterized SQL, least-privilege roles, explicit transactions, and observable slow/failing operations.

Use expand/migrate/contract schema changes. Validate lock duration, mixed-version compatibility, rollback/forward remediation, backup, PITR, and restore in an isolated environment before persistent migration.

## Consequences

- Job throughput and database workload share capacity and must be measured.
- Workers need lease fencing, idempotency, dead-letter handling, and reconciliation.
- Persistent migrations remain human-gated.

## Approval criteria

Select PostgreSQL version/topology/operator and migration tool; approve capacity, HA, maintenance, RPO/RTO, backup/PITR, encryption/key custody, restore order, and recovery-test cadence.
