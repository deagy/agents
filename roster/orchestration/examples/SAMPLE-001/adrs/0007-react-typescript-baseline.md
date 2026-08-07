# ADR 0007: React and TypeScript Baseline

- Status: Proposed — tooling selections deferred
- Owners: Frontend and product owners

## Context

React and TypeScript are team preferences, but framework, build tool, package manager, styling/component system, browser support, accessibility target, and test stack are undecided.

## Decision

Use React with TypeScript and semantic web-platform behavior. Keep the application compatible with the same-origin BFF contract. Do not establish organization-wide tooling choices in this project without a separate approved evaluation.

Require explicit idle, validating, uploading, processing, complete, rejected, error, authorization-expired, retry, and cancelled states. Provide keyboard operation, focus management, status announcements, responsive layout, output encoding, safe error handling, and typed API contracts.

## Consequences

- Scaffolding cannot begin until project-local tooling and supported browsers are selected.
- Frontend checks improve usability only; the server remains authoritative for validation and authorization.

## Approval criteria

Select package manager, Node version, framework/build tool, styling/component system, unit/component/browser test stack, supported browsers, and accessibility target. WCAG 2.2 AA is the recommended minimum target.
