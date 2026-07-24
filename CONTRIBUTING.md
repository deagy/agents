# Contributing

This repository is hosted on GitHub. Contributions are reviewed through GitHub
pull requests and validated by the repository's GitHub Actions checks. The
Secure Cloud target profile may describe GitLab-based customer environments;
that does not change this repository's contribution workflow.

## Before changing files

Read:

1. [AGENTS.md](AGENTS.md) for repository rules.
2. [IDENTITY.md](IDENTITY.md) for the suite's informational orientation.
3. [agents/README.md](agents/README.md) for the source layout.
4. [agents/RUNBOOK.md](agents/RUNBOOK.md) for orchestration and handoffs.

Keep role definitions and `agents/catalog.yaml` synchronized. Preserve the
separation between authors, independent reviewers, human approvers, evidence
curators, and release operators.

## Typical change flow

```text
understand scope -> make a focused change -> run relevant checks
-> regenerate packaged artifacts when required -> inspect the diff
-> open a GitHub pull request -> obtain independent review -> merge
```

Do not commit or push secrets, raw chat exports, real documents, credentials,
databases, object data, Terraform state, rendered secrets, or generated
credentials. Do not make persistent-environment or production changes as part
of repository validation.

## Documentation changes

For documentation-only work:

- use approved implementation, policy, and runbook sources;
- identify the intended audience and prerequisites;
- preserve security warnings and authority boundaries;
- link to the canonical source rather than duplicating long procedures;
- avoid documenting proposals as current behavior;
- check local Markdown links and command names before opening the PR.

Edit canonical role and policy documentation under `agents/`. Files under
`plugins/secure-cloud-agents/` may be generated artifacts. When a source change
requires regeneration, follow the repository command in `AGENTS.md`, inspect
the generated diff, and include the reason in the pull request.

## Pull request checklist

- [ ] The scope and affected decisions are described.
- [ ] Security, authority, lifecycle, and generated-artifact implications are
      called out.
- [ ] Relevant tests or documentation checks were run.
- [ ] Role definitions and catalog entries remain synchronized when applicable.
- [ ] Independent review is assigned for implementation or policy changes.
- [ ] No secrets or sensitive source material are included.
- [ ] Human-only approvals remain explicit and are not inferred from agent work.
