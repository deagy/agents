---
name: initialize-agentic-sdlc
description: Bootstrap the portable Agentic SDLC in a repository by detecting project characteristics, generating a minimal project overlay, and validating safe defaults. Use when onboarding a repository, creating `.agentic-sdlc/`, selecting a starter profile, or refreshing detected commands without inventing governance decisions.
---

# Initialize Agentic SDLC

1. Locate the plugin root from this skill directory. Use `../../scripts/agentic_sdlc.py`; do not copy the kernel into the project.
2. Inspect repository instructions and existing build, test, CI, deployment, and infrastructure files. Preserve existing user changes.
3. Run `init --help`, then run `init` with only supported flags. Use detection as a proposal, not authority.
4. Review the generated `.agentic-sdlc/` overlay. Keep human authorities unassigned, uncertain applicability `unknown`, and uncertain persistent or production environments unresolved. Never infer risk acceptance, compliance scope, production authorization, or approval evidence.
5. Keep project-owned run records and evidence references in the overlay; keep portable behavior in the plugin.
6. Run the CLI `validate` command. Report detected facts, unresolved decisions, created files, and blockers.

Initialization makes planning immediately usable. It must fail closed for approvals or gates whose authority, applicability, evidence, or environment binding is unresolved.
