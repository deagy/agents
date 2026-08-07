# ADR 0001: Same-Origin BFF for OIDC

- Status: Proposed — human approval required
- Owners: Application architecture and security

## Context

The frontend-only ingress proposal conflicts with a browser that directly calls a private API. Browser-held tokens also increase XSS and storage risk.

## Decision

Use a same-origin BFF. It serves or fronts the React application, performs OIDC Authorization Code with PKCE, keeps tokens server-side, issues an opaque Secure/HttpOnly session cookie, enforces CSRF protection, and proxies authorized `/api/*` traffic to the private document API.

## Consequences

- The document API and OIDC tokens remain private.
- BFF sessions require a shared, protected store and explicit idle/absolute expiry.
- Cookie, CSRF, CORS, CSP, redirect, logout, refresh, and revocation behavior become testable.
- The BFF adds an availability and streaming hop that requires limits, timeouts, and observability.

## Approval criteria

Approve issuer/audience, redirect URIs, claim mapping, session durations, cookie attributes, CSRF mechanism, BFF implementation ownership, and failure/logout behavior.
