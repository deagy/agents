# Dispatch Contract

Read this contract before dispatching any selected role.

## Required input per agent

Each dispatch prompt must include:

- role name and exact `AGENT.md` path;
- task ID, objective, execution mode, classification, scope, exclusions, and acceptance criteria;
- exact files, source revision, plan, artifact digest, target, or environment when applicable;
- applicable shared policies, workflow, quality gates, and escalation policy;
- selector-emitted lifecycle `required_quality_gates`, mutation-oriented `human_gates`, and current gate-state records;
- the planned Python knowledge-store invocation and its result status; resolve its Python 3.10+ launcher at execution and preserve the supplied argv without shell interpretation;
- retrieved passages with `source`, `conversation_id`, `message_id`, `chunk_id`, `content_hash`, `created_at`, and `classification` citations, plus the retrieved bundle and its integrity hash as point-in-time evidence;
- nested citation `source_uri` omitted or redacted by default, and included only when separately authorized and necessary because it may reveal a local path;
- explicit permitted and prohibited actions;
- expected response template or schema;
- named receiving role or human owner.

Do not dispatch an implementation or review agent when its required artifact is absent. Mark that role `deferred` with the missing prerequisite.

## Safe prompt template

```text
Act as <role> using <role AGENT.md>.

Task: <task ID and objective>
Mode: <planning-review-only | scoped-repository-edit>
Classification: <classification>
Scope: <exact paths/artifacts/revision/target>
Exclusions: <explicit exclusions>
Acceptance criteria: <criteria>

Follow: <shared policies, workflow, gates, contracts>
Knowledge context: <invocation and available/empty/unavailable/unauthorized status>

Permitted: <bounded actions>
Prohibited: production or persistent mutations, destructive actions,
risk acceptance, policy exceptions, merge/push, and self-approval unless an
authorized human explicitly grants the specific action.

Return: <required template/schema>, evidence, disposition, unresolved risks,
and handoff to <receiver>.
```

## Wave and gate rules

- Run agents in parallel only when their inputs and write scopes are independent.
- Serialize agents that depend on another role's final artifact.
- Preserve separation between authors, reviewers, risk owners, and production approvers.
- Treat `needs-information`, `request-changes`, and `blocked` as non-approval.
- Stop release progression for unresolved critical/high risk, ambiguous targets, stale artifacts, mismatched revisions, or missing required evidence.
- Require an authorized human before persistent environments, production, destructive operations, database migration application, Terraform apply/state mutation, privileged identity or key changes, risk acceptance, or policy exceptions.

## Consolidated run record

Use `agents/orchestration/run-record.schema.json` as the authoritative structure when saving a run record. At minimum, preserve this summary together with the schema-required lifecycle, impact-profile, gate, evidence, exception, and invalidation fields:

```yaml
task_id: <id>
mode: <mode>
selection_status: <ready|needs-triage>
agents:
  completed: []
  blocked: []
  deferred: []
knowledge:
  status_by_agent: {}
findings: []
human_gates: []
required_quality_gates: []
artifacts: []
validation: []
disposition: <approve|request-changes|needs-information|blocked|plan-only>
next_safe_action: <action>
```
