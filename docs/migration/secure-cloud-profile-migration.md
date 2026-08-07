# Secure-Cloud Profile Migration

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
**Location**: `/home/deagy/sdk/cadre-profile-secure-cloud/`
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
