# Agentic SDLC Artifact and Traceability Contract

This contract applies to intent, requirements, architecture, governance, data,
security, crypto, implementation, test, evidence, release, runtime, and backlog
artifacts. Run records index these artifacts; they do not replace primary human
approval evidence.

## Required artifact metadata

Each artifact has:

- A stable repository-unique `artifact_id`, artifact type, version, lifecycle
  state, owner, classification, and creation/update timestamps.
- Exact source revision and, when immutable, a cryptographic digest and digest
  algorithm. Mutable references cannot serve as approval evidence.
- Author identities, AI-generated or AI-assisted provenance, generating agent
  and model/tool identity when available, inputs used, and human edits/review.
- Target component, platform phase, environment, and SQS impact-profile
  reference where applicable.
- Upstream and downstream links expressed as relationship, target stable ID,
  target version or digest, and rationale.
- Evidence references with location, media type, classification, retention
  obligation, integrity hash, producer, and collection time.

## Traceability rules

1. Intent outcomes trace to requirements; requirements trace to architecture,
   controls, implementation, tests, findings, and evidence. Downstream artifacts
   link back to the exact upstream version.
2. Links are typed (`derives-from`, `satisfies`, `implements`, `verifies`,
   `mitigates`, `evidences`, `supersedes`, or `invalidates`) and bidirectional.
3. A missing required reverse link, stale version, broken reference, or digest
   mismatch blocks the consuming gate.
4. Superseded artifacts remain preserved. A material change creates a new
   version, invalidates the earliest affected gate and all dependent gates, and
   records the required re-entry gate.
5. Findings trace to the affected requirement/control/artifact and to their
   disposition. Exceptions trace to the finding and accountable human approval.

## Independence and authority

Every reviewed artifact identifies preparers and independent verifiers. The
verifier declares that they are not a preparer and made no material correction.
A person or agent who makes a material correction is added as an author and
cannot approve that artifact revision. JSON Schema can require these declarations
but cannot compare arbitrary identity strings; orchestration must enforce identity
inequality semantically.

Gate records declare conditional authority applicability instead of silently
omitting a decision maker. Applicable authorities must be satisfied by the
declared verifier or a matching human approval; unknown applicability fails
closed.

Agents may draft, implement, test, review, and index evidence only within their
role authority. Human-only priority, scope, risk acceptance, exception, key,
persistent-mutation, production, and release decisions remain external approval
records referenced by the run record.
