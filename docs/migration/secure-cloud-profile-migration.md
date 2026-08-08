# Secure-Cloud Profile Migration

> [!IMPORTANT]
> **Superseded — this migration was reversed.** The monorepo merge folded
> `deagy/cadre-profile-secure-cloud` back in; its `profile.json` was
> byte-identical to `provider/profiles/secure-cloud/`, and the separate
> repository existed only for CI to drift-check one copy against the
> other. That repository is archived. See
> [Monorepo migration](monorepo-migration.md).
>
> Kept as a record of the reasoning at the time.

## Overview

The `secure-cloud` provider profile has been migrated from `cadre/provider/profiles/secure-cloud/` to a separate repository: **cadre-profile-secure-cloud**.

## Rationale

Moving the secure-cloud profile to a separate repository:

1. **Separation of Concerns**: The profile is a specialized configuration that extends the generic profile. It has its own versioning and release cycle.
2. **Reduced Scope**: The main cadre repository focuses on core framework functionality without cloud-specific profiles.
3. **Independent Deployment**: The profile can be updated and released independently of the core framework.

## Migration Status

- ✅ Profile data (`profile.json`) copied to new repository
- ✅ README created with usage documentation
- ✅ Repository initialized and committed
- ⏳ References in main cadre repo updated

## New Repository

**Repository**: `cadre-profile-secure-cloud`
**Upstream**: <https://github.com/deagy/cadre-profile-secure-cloud>
**Local checkout**: a sibling directory of this repository; the exact path is
developer-specific and deliberately not recorded here, since this file is
copied verbatim into the published plugin distribution.
**Contents**:
- `profile.json` - Main profile definition
- `README.md` - Usage documentation

## Usage

To use the secure-cloud profile:

1. Clone the profile repository
2. Reference it in your Cadre configuration:
   ```yaml
   provider:
     profile: secure-cloud
     path: /path/to/cadre-profile-secure-cloud/profile.json
   ```

3. The profile extends `generic` and adds cloud-specific agents and routing rules.

## Agents Included

- frontend-engineer, backend-engineer
- infrastructure-provisioner, cicd-engineer
- black-box-tester, end-user-tester
- escalation-manager, cost-capacity-planner, finops-engineer
- secrets-identity-engineer, policy-as-code-engineer
- database-reliability-engineer
- infrastructure-reviewer, pipeline-security-reviewer, supply-chain-security-reviewer
- technical-writer, knowledge-store-steward, api-contract-engineer
- accessibility-reviewer

## Routing Rules

The profile includes specialized routing for:
- Frontend/Backend development
- Infrastructure provisioning (Proxmox, Talos, Kubernetes, Helm)
- CI/CD pipeline engineering
- Security and compliance
- Database operations
- Cost management
- Documentation

## Version

The profile version (0.3.0) aligns with the Cadre framework version.

## Related

- **cadre** - Core framework and CLI
- **cadre-lifecycle** - Cline plugin for lifecycle management
- **agentic-sdlc** - Software Development Lifecycle governance
