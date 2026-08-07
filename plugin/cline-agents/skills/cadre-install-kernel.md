---
name: cadre-install-kernel
description: Install the Agentic SDLC lifecycle kernel that the G1-G10 governance skills need. Use when a session reports the kernel is missing or out of range, when `cadre sdlc` fails with an install pointer, or when a user asks to set up, install, repair, or upgrade lifecycle governance.
canonicalSource: skills/cadre-install-kernel/SKILL.md
---

> Cline packaging note: this skill's instructions describe this repository's own `roster/`-layout tooling in the abstract (the role catalog, routing configuration, and selector this plugin bundles) -- they are not literal paths to look up in an arbitrary target project. When dispatching, use `start_subagent`/`dispatch_selected_roles`/`bin/cadre select` rather than reading these files directly.


# Install the lifecycle kernel

The lifecycle plugins drive gate decisions through `cadre sdlc`, a thin
pass-through to a separately installed `agentic-sdlc` kernel. This skill
installs a copy the plugin owns and manages.

**This is the only thing that installs the kernel.** The `SessionStart` hook
only detects and reports — it never installs. That split is deliberate: a
hook that runs `pip install` from a network URL on every session start,
before the human has asked for anything, is a supply-chain problem, not a
convenience. Installation stays an explicit act.

## What it does

```sh
cadre-install-kernel --skip-init      # install/verify the kernel only
cadre-install-kernel --dry-run        # print what it would do, change nothing
```

`cadre-install-kernel` is on the Bash tool's PATH whenever this plugin is
enabled. It creates a virtualenv under this plugin's own data directory
(`${CLAUDE_PLUGIN_DATA}/kernel`) and installs the kernel version the plugin's
`kernel-compatibility.json` declares.

Report `--dry-run` output to the human before installing if they have not
already asked for the install explicitly.

## What it will not do

- **It never touches a kernel the human owns.** If `AGENTIC_SDLC_BIN` is set,
  that binary is used as-is; if it is outside the supported range, this stops
  and says so rather than substituting a different one.
- An `agentic-sdlc` on `PATH` that is out of range is **left alone** — the
  plugin installs its own copy alongside instead. It does not upgrade,
  downgrade, or uninstall anything the operator installed.
- Nothing outside `${CLAUDE_PLUGIN_DATA}` is written. Deleting that directory
  fully undoes the install.
- No shell profile is modified. The plugin's `bin/agentic-sdlc` shim reaches
  the managed copy directly, so there is no `PATH` change to make and no new
  shell to start.

## After installing

```sh
cadre sdlc --version                  # confirm the kernel resolves
cadre sdlc validate --root .          # confirm it can read the project
```

To set up a project's `.agentic-sdlc/` overlay, use the `lifecycle-onboarding`
skill rather than running `init` directly — assigning the human authorities is
a decision a person has to make, and that skill walks through it.

## If it fails

- **No Python 3.10+** — the shim reports this; nothing else can proceed.
- **Network blocked** — the install fetches from GitHub. In an air-gapped
  environment, pre-seed `${CLAUDE_PLUGIN_DATA}/kernel` from an internal
  mirror, or install the kernel yourself and set `AGENTIC_SDLC_BIN`.
- **A policy forbids this entirely** — set the plugin's `kernelInstall`
  option to `off` and provide `AGENTIC_SDLC_BIN`; the detection hook stays
  quiet and nothing is ever installed.
