# Cadre plugin

The installable Claude Code / Codex CLI distribution of **Cadre**: 71
specialist roles, nine suite skills, the orchestration runtime, the
knowledge-store runtime, and an external Agentic SDLC provider
(`provider.json` is the versioned source of truth — see `version` and
`kernel_compatibility` there rather than this prose). The package is
self-contained: once installed it depends on no source checkout.

This repository is one of three:

| Repository | Owns |
| --- | --- |
| [`deagy/cadre`](https://github.com/deagy/cadre) | The **register** — role definitions, catalog, routing, and the generator. The source of everything generated here. |
| `deagy/cadre-lifecycle` (this repository) | The **plugin implementations** — the generated distribution above, plus the hand-authored package assets, the Cline plugin under `cline/`, and optional, separately-owned Agentic SDLC lifecycle-governance plugins. Successor to the now-archived `deagy/cadre-plugin`. |
| [`deagy/agentic-sdlc`](https://github.com/deagy/agentic-sdlc) | The **lifecycle kernel** — G1–G10 gate schemas, run-record validation, gate authority. |

## Installing

**Claude Code** adds this marketplace straight from GitHub — no clone of your
own. Pin to a release; check [the
releases](https://github.com/deagy/cadre-lifecycle/releases) for the current tag
rather than trusting the one written here:

```text
/plugin marketplace add deagy/cadre-lifecycle@v0.7.0
/plugin install cadre@cadre-lifecycle-team
```

Without `@<tag>` you track `main`, which moves. A *marketplace* source accepts
a branch or tag but not a commit SHA, so the pin is only as immutable as the
tag itself. `owner/repo` shorthand clones over SSH by default; set
`CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` for HTTPS.

**Codex** installs from a local checkout, so clone at the tag first:

```sh
git clone --branch v0.7.0 https://github.com/deagy/cadre-lifecycle.git
codex plugin marketplace add /path/to/cadre-lifecycle
codex plugin add cadre@cadre-lifecycle-team
```

**Verify before installing** (optional, recommended for anything you did not
build yourself — this drops 71 role-instruction files and a `bin/cadre` onto
your `PATH` at user scope). See [Verifying a
release](#verifying-a-release) — as of this writing that section is aspirational
for this successor repository; install from the tagged git checkout or the
pinned marketplace add above instead:

```sh
git clone --branch v0.7.0 https://github.com/deagy/cadre-lifecycle.git
codex plugin marketplace add /path/to/cadre-lifecycle   # or /plugin marketplace add /path/to/cadre-lifecycle
```

**Cline** installs the hand-authored `cline/` plugin (the single `agents_select`
tool; see that directory's own notes on what it can and can't do) from a git
source:

```sh
cline plugin install --git https://github.com/deagy/cadre-lifecycle --force
```

or from a local checkout for development:

```sh
git clone --branch v0.7.0 https://github.com/deagy/cadre-lifecycle.git
cline plugin install /path/to/cadre-lifecycle --force
```

If `agents_select` doesn't show up in a session after installing or updating
the plugin, it is very likely **not** a plugin problem: Cline's local `cline
hub` daemon enumerates installed plugins once, at its own startup, and does
not notice plugins installed or changed afterward. Check for this with
`cline doctor` (an `agents_select`-less session alongside a `hub uptime`
older than the plugin's install time is the signature) and clear it with
`cline doctor fix`, which restarts the daemon so it re-scans
`~/.cline/plugins/_installed/`.

### The lifecycle kernel

This repository does not contain the lifecycle kernel; that remains a
separately versioned dependency, and it is not installed as a plugin. Clone it
and put its CLI on `PATH` (or set `AGENTIC_SDLC_BIN`):

```sh
git clone https://github.com/deagy/agentic-sdlc.git
git -C agentic-sdlc checkout <current tag>   # see that repo's releases; don't hardcode
export AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc
```

`provider.json` contributes the `secure-cloud` profile, package-relative role
catalog, and optional impact extensions to Agentic SDLC v0.3.x. The repository
launcher injects it automatically:

```sh
AGENTIC_SDLC_BIN=/path/to/agentic-sdlc/bin/agentic-sdlc \
  cadre sdlc init --root /path/to/project --profile secure-cloud
```

The generated package contains no source-checkout paths. Role wrappers embed
their role and shared-policy instructions; skills and runtime files live under
`skills/` and `suite/`.

## GitHub review-backed approvals

The lifecycle commands are supplied by the standalone Agentic SDLC plugin and
are exposed here through `cadre sdlc`. To require GitHub reviews for human
gates, configure the target project's `.agentic-sdlc/project.json`:

```json
"approval_sources": {
  "human_gate_default": "github-review",
  "allow_manual_fallback": false
}
```

Bind each applicable authority to its GitHub login, then fetch and record an
approval with an authenticated GitHub CLI:

```sh
cadre sdlc approve-from-github-pr \
  --root /path/to/project --task-id TASK-42 --gate G2 \
  --role product_owner --repo OWNER/REPO --pr 42 --commit-sha "$GITHUB_SHA"
```

The command selects the latest matching `APPROVED` review and fails closed on
missing access, missing approval, identity mismatch, or revision mismatch. Run
`cadre sdlc validate` afterward. A valid approval advances the lifecycle
record to the next applicable gate; it does not approve deployment or accept
risk.

## Codex role wrappers

Codex discovers custom agents only under project `.codex/agents/` or global
`~/.codex/agents/`. Install the staged, namespaced wrappers safely:

```sh
cadre bootstrap-codex
```

The generated IDs and filenames use `agents-<role>`. The command
never touches legacy bare `<role>.toml` files and refuses to overwrite an
existing namespaced file unless it carries this generator's provenance marker.
Legacy bare global files may be removed manually after confirming nothing still
dispatches them; installation never deletes them. A project-local bare
`.codex/agents/<role>.toml` remains the preferred override.

Claude Code discovers `agents/*.md` directly from the plugin.

## Regeneration

**Generated — never hand-edit here.** `skills/`, `roster/`, `codex-agents/`,
`suite/`, `bin/cadre`, `agent-catalog.json`, `provider.json`, `profiles/`,
`extensions/`, and **`README.md` (this file)** are all produced from
[`deagy/cadre`](https://github.com/deagy/cadre). Editing any of them here
breaks this repository's `validate.yml` with a drift failure. Their sources in
the register are `roster/`, `.agents/skills/`, `provider/`, and
`packaging/plugin-README.md` — change them there and regenerate:

```sh
git clone https://github.com/deagy/cadre.git
git -C cadre checkout "$(grep -v '^[[:space:]]*#' /path/to/cadre-lifecycle/cadre-ref.txt \
  | grep -v '^[[:space:]]*$' | head -1)"
cadre/bin/cadre generate-plugin --output /path/to/cadre-lifecycle
```

Check out exactly the revision `cadre-ref.txt` names, not a release tag:
`.github/workflows/validate.yml` runs the same command with `--check` against
that revision, so regenerating from anything else produces a diff CI rejects.
Picking up register changes is a deliberate act: bump `cadre-ref.txt` and
commit the regenerated diff in the same pull request.

**Hand-authored here** — the only files regeneration never touches: the two
plugin manifests under `.claude-plugin/` and `.codex-plugin/` (which carry the
release version), the marketplace manifests, `cadre-ref.txt`, `tools/`,
`.github/`, and the Cline plugin under `cline/`.

Note that the drift check covers only the generated set listed above. The
hand-authored files — including `cline/`'s own `package.json` and lockfile —
are outside it and need ordinary review.

## Verifying a release

Installing this plugin puts 71 role-instruction files and a `bin/cadre` onto
`PATH` at user scope in your agent session, so it is worth checking what you
are installing came from the build you expect. Cloning gives you commit
integrity; it says nothing about which workflow produced the content.

In the now-archived `deagy/cadre-plugin`, each release attached a source
tarball and an SBOM for the Cline plugin's npm dependency tree, both with
SLSA build provenance signed through GitHub's hosted Sigstore instance,
verifiable with the GitHub CLI (`gh release download`/`gh attestation
verify`). That confirmed the tarball was built by that repository's
`release.yml` at the tagged commit, and not assembled elsewhere.

**`deagy/cadre-lifecycle`'s current `release.yml` does not yet reproduce
this** — its releases are a plain git tag plus a GitHub Release whose notes
are that version's `CHANGELOG.md` entry, with no attached tarball, SBOM, or
attestation. Until that gap is closed, verify by installing from a tagged git
checkout (commit integrity only) rather than expecting a downloadable,
attestable artifact.

The generated Cadre package itself carries no third-party dependencies (Python
standard library and Markdown only), which is why the SBOM covers `cline/`
specifically: that npm tree is the plugin's entire external dependency
surface.

## Releasing

The version lives in both plugin manifests and they must always agree. Set
them together:

```sh
python3 tools/plugin_version.py --set 0.7.0
```

`.github/workflows/release.yml` tags and publishes once that bump lands on
`main`.
