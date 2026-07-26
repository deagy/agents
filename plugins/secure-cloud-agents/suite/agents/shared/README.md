<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# `agents/shared/` — global defaults and per-project overrides

Every role's `AGENT.md` points at a subset of the files in this directory as
required reading (stack choices, autonomy policy, security baseline, and so
on), and `agents/orchestration/src/generate_global_plugin.py` embeds them
directly into every packaged role's instructions. Those files are this
repository's **global defaults**. A project using these agents can extend or,
where it makes sense, override them without editing this checkout, by
placing a same-named file at `.agents/shared/<filename>` in its own tree.

## Precedence

1. Explicit task instructions from the human or orchestrator (unchanged —
   see `operating-principles.md`).
2. A project-local overlay at `.agents/shared/<filename>`, found by walking
   up from the current directory to the nearest `.git` (the same convention
   `agents/knowledge-store/src/config.py` uses for its project-local
   `config.json`).
3. The global default in this directory.

Resolve the effective value with `agents resolve-shared <filename>` (see
`agents/shared/src/resolve.py`), run from anywhere inside the target
project. It fails closed: a malformed overlay is an error, not a silent
fallback to the default.

## Merge rule by file type

- **Structured files** (`*.yaml`, `*.json` — `team-profile.yaml`,
  `library-standards.yaml`, `agent-autonomy.yaml`,
  `control-mapping-template.yaml`, `sqs-impact-profile.yaml`): deep-merged,
  overlay wins per key. Keys the overlay doesn't mention keep the global
  default.
- **`agent-autonomy.yaml` specifically**: the merge is narrowing-only. This
  file is a safety control, not a preference, so a project overlay may move
  a value toward *more* restrictive (e.g. `allowed` → `human_approval`) but
  resolving raises an error if an overlay tries to loosen a `never` default
  or turn any other restricted default into `allowed`. An overlay also can't
  touch `policy_version` or `default_rule` (the fixed contract) or reference
  a key the global default doesn't define.
- **Prose files** (`*.md` — `operating-principles.md`,
  `technology-standards.md`, `cloud-guardrails.md`,
  `secure-development-policy.md`, `risk-severity-model.md`,
  `knowledge-use-policy.md`, `definition-of-done.md`): additive, never
  replaced. If an overlay exists, the resolved text is the global default
  plus an appended `## Project addendum` section. On a direct conflict
  between the default and the addendum, the more specific/restrictive
  instruction wins, per the existing rule in `operating-principles.md`.

## Where overlays live

```
<project-root>/
└── .agents/
    └── shared/
        ├── team-profile.yaml          # overrides agents/shared/team-profile.yaml
        ├── agent-autonomy.yaml        # narrowing-only overrides
        └── technology-standards.md    # appended as a project addendum
```

Only files a project actually wants to extend or override need to exist
under `.agents/shared/`; anything absent resolves straight to the global
default.

## The SQS impact profile

`sqs-impact-profile.yaml` defines the impact-category and BOM vocabulary for
an external organization/platform this repository deliberately does not
define the semantics of (see `docs/terminology.md`'s SQS entry) — a
consuming project supplies its own authorized definitions and owners, and
`unknown` blocks the relevant gates by design in whatever system enforces
that lifecycle (this repository's own run-record/quality-gate machinery was
intentionally removed in favor of the standalone Agentic SDLC kernel; see
`bin/agents sdlc`). A project overlay of this file follows the same
structured-file merge rule as any other shared default — it can pre-fill a
project's own applicability decisions as a starting template, not just leave
every category `unknown`.
