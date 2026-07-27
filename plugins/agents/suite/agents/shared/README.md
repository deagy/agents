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
  `control-mapping-template.yaml`, `platform-impact-profile.yaml`): deep-merged,
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

## Generating overlays with `agents init`

Rather than hand-authoring `.agents/shared/<filename>` overlays from scratch,
run `agents init --target <project-root>` (see `agents/shared/src/
init_project.py`) to be guided through RG-A (stack/tooling opinions), RG-B
(governance/autonomy narrowing, with a closed allowlist — never free text —
for `agent-autonomy.yaml`), and RG-C (guided `platform-impact-profile.yaml`
fill-in). Nothing is written without `--force`; omitting it previews only.
Every generated overlay is validated by resolving it exactly as `agents
resolve-shared` would before success is reported.

Answer the run either non-interactively with `--answers <file.yaml>` (a
`schema_version: 1` file in the shape `init_project.py`'s module docstring
documents — the same shape `--print-answers` echoes, so a prior run's
answers are directly reusable) or interactively with `--interactive`
(exactly one of the two is required). `--stack <preset-id>` names a starter
preset from `agents/shared/init-presets/*.yaml` — a static, human-reviewed,
RG-A-only fragment (it can never touch `agent-autonomy.yaml` or
`cloud-guardrails.md`) whose values are shown as prompt defaults in
`--interactive` mode, or merged under an `--answers` file (the answer file's
own values win). `--sections` restricts the run to a comma-separated subset
of `rg-a-stack,rg-b-governance,rg-c-platform` (default: all three).

Pass `--print-answers` to echo the resolved answer set (after validation)
alongside the write preview, so a run is reproducible from a saved answer
file. `agent-autonomy.yaml` and `cloud-guardrails.md` fields are redacted in
that echo to a per-field `accepted`/`rejected` status plus a sha256 hash
rather than the raw value — the raw value is never printed to stdout/stderr,
only ever written to the audit log (or the resulting overlay file itself) as
a hash or as real file content.

`technology-standards.md` and `cloud-guardrails.md` overlays use a managed
block (`<!-- agents-init:managed:start/end -->`): re-running `agents init`
against the same project accumulates new addendum entries/guardrail bullets
onto whatever a prior run already wrote there instead of replacing it
(exact-duplicate bullets are deduped), and any content a human has manually
added outside the managed block is left untouched.

Every field an answer set supplies a value for must have a corresponding
`field_decisions` entry recording a `kept`/`overridden`/`deferred` status and
a `category` of either `stack` (team-profile.yaml/library-standards.yaml/
technology-standards.md/platform-impact-profile.yaml) or `governance`
(agent-autonomy.yaml/cloud-guardrails.md). `agents init` fails closed (no
writes) if a touched field is missing a decision entry, or if a field's
declared category doesn't match which file it actually touches.

## The platform impact profile

`platform-impact-profile.yaml` defines the impact-category and BOM vocabulary for
an external organization/platform this repository deliberately does not
define the semantics of (see `docs/terminology.md`'s platform entry) — a
consuming project supplies its own authorized definitions and owners, and
`unknown` blocks the relevant gates by design in whatever system enforces
that lifecycle (this repository's own run-record/quality-gate machinery was
intentionally removed in favor of the standalone Agentic SDLC kernel; see
`bin/agents sdlc`). A project overlay of this file follows the same
structured-file merge rule as any other shared default — it can pre-fill a
project's own applicability decisions as a starting template, not just leave
every category `unknown`.
