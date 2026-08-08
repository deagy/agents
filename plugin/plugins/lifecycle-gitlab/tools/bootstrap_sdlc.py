#!/usr/bin/env python3
"""Install and configure the external Agentic SDLC kernel for this plugin.

`bin/cadre sdlc` shells out to a separately installed `agentic-sdlc`
executable and simply fails with an install pointer if one isn't already
resolvable -- by design, the kernel is never vendored into an installed
plugin (see `provider.json`'s `kernel_compatibility`). This script is the
deliberate, opt-in step a human runs once to close that gap: it installs the
kernel version this plugin's compatibility data declares, then runs
`agentic-sdlc init` against a target project using this plugin's own
`provider.json`.

Resolution is ordered by *who owns the install*, which is what decides
whether this script may touch it:

  1. `AGENTIC_SDLC_BIN`  -- the human named this binary explicitly. Used if
     compatible; if not, this fails closed rather than substituting a
     different one behind their back.
  2. the managed copy    -- a venv under `${CLAUDE_PLUGIN_DATA}/kernel` that
     this plugin created and therefore may install, upgrade, or downgrade
     freely to satisfy the window.
  3. `agentic-sdlc` on `PATH` -- the operator's own install. Used if
     compatible. If not, it is left strictly alone and the managed copy is
     used instead.

That third case used to be a hard stop: an out-of-range install on PATH
produced "not reinstalling automatically" and left the user with a broken
plugin and no way forward except uninstalling their own tool.

Installation prefers the managed venv (stdlib `venv` + `pip`), falling back
to pipx when there is no plugin data directory to install into, or when this
Python cannot create a venv at all -- Debian and Ubuntu ship `ensurepip` in a
separate `python3-venv` package, so a stock system Python there fails at
venv creation. If neither route is available the error names both fixes,
since either one resolves it.

The venv removes the "run `pipx ensurepath`, start a new shell, and re-run"
dead end: pipx installs into a shared bin directory that may not be on `PATH`
yet, whereas the plugin's own `bin/agentic-sdlc` shim reaches the venv
without the user's shell profile being involved at all.

It intentionally does *not* wire into `bin/cadre` as a subcommand.
`generate_global_plugin.py` fully regenerates `bin/cadre` from scratch on
every `cadre generate-plugin` run -- see that generator's
`GENERATED_TOP_LEVEL` -- so any hand-added case there would be silently
deleted on the next regeneration. `plugin/tools/` is not part of that
generated set (see `plugin_version.py`, the existing precedent for a
hand-authored script invoked directly rather than through `bin/cadre`).

    python3 plugin/tools/bootstrap_sdlc.py                    # install (if needed) + configure this project
    python3 plugin/tools/bootstrap_sdlc.py --dry-run          # report what would happen, change nothing
    python3 plugin/tools/bootstrap_sdlc.py --skip-init        # install/verify the kernel only
    python3 plugin/tools/bootstrap_sdlc.py --root /path/to/project --profile secure-cloud

Never modifies, replaces, or uninstalls an `agentic-sdlc` the human owns --
only the managed copy under `${CLAUDE_PLUGIN_DATA}` is ever written to, and
removing that directory fully undoes anything this script did.

Before the monorepo merge this file existed three times over -- once per
lifecycle plugin, byte-identical apart from four docstring lines, held in
sync by hand.

This is now the single hand-maintained copy. Each lifecycle plugin still
ships its own `tools/bootstrap_sdlc.py`, because a plugin must be installable
without the others, but those three are *generated* from this file at build
time (`generate_global_plugin.py`'s BOOTSTRAP_SOURCE -> BOOTSTRAP_TARGETS)
and are checked against it by `cadre generate-plugin --check` and by
`test_plugin_duplication_health.py`. Edit this file; never edit a copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Sequence

# Two locations have to work, and before the monorepo merge only one did.
#
# In a checkout this file sits at plugin/tools/, and the compatibility data
# lives in the register's own provider manifest at provider/provider.json.
#
# In an *installed plugin* it sits at <plugin>/tools/, and there is no
# repository around it at all. That case used to be unreachable: the three
# lifecycle plugins are packaged from plugins/lifecycle*/ subdirectories,
# so provider.json -- a repository-root file -- was never shipped inside
# them, and the old `parents[3]` walk climbed out of the plugin entirely.
# read_kernel_compatibility() then died with "missing provider manifest" for
# every plugin user, at any path. The build now emits a small derived
# kernel-compatibility.json next to this script, which is checked first.
_HERE = Path(__file__).resolve().parent
PACKAGED_COMPATIBILITY_PATH = _HERE / "kernel-compatibility.json"
REPO_ROOT = _HERE.parent.parent
PROVIDER_MANIFEST_PATH = REPO_ROOT / "provider" / "provider.json"

# The kernel now ships from the monorepo; deagy/agentic-sdlc is archived.
#
# The tag is `kernel-v<version>`, not `v<version>`. The monorepo inherited
# 25 bare `v*` tags from the pre-merge deagy/cadre (v0.1.1 through v0.16.0),
# and those point at old-cadre history that has no kernel/ directory at all --
# so `@v0.13.0#subdirectory=kernel` resolves to a real tag and then fails to
# find anything to install. Component-prefixed tags are what release.yml
# publishes precisely to avoid that collision.
AGENTIC_SDLC_GIT_URL = "https://github.com/deagy/cadre.git"
AGENTIC_SDLC_SUBDIRECTORY = "kernel"
AGENTIC_SDLC_TAG_PREFIX = "kernel-v"
RELEASE_DOWNLOAD_BASE = "https://github.com/deagy/cadre/releases/download"
NETWORK_TIMEOUT_SECONDS = 60

# Indirected so tests never reach the network.
_urlopen = urllib.request.urlopen


class KernelIntegrityError(Exception):
    """A downloaded artifact did not match its published checksum."""

# Claude Code exports each `userConfig` option to hook processes as
# CLAUDE_PLUGIN_OPTION_<KEY>, uppercased. Shell-form hook commands are not
# allowed to substitute ${user_config.*} (a configured value interpolated
# into a shell command would be executed by that shell), so reading the
# environment is the supported route, not a workaround.
KERNEL_INSTALL_ENV_VAR = "CLAUDE_PLUGIN_OPTION_KERNELINSTALL"
PROFILE_ENV_VAR = "CLAUDE_PLUGIN_OPTION_PROFILE"
MODE_AUTO, MODE_SYSTEM, MODE_OFF = "auto", "system", "off"

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# Distinct from a plain non-zero exit: the venv could not be *created*,
# so falling back to pipx is meaningful. A pip failure inside a venv that
# did get created is a real error and propagates as itself.
VENV_UNAVAILABLE = 127

# Overridable so tests (and, in principle, a caller with an unusual
# environment) don't have to actually invoke pipx/agentic-sdlc as a subprocess.
_run = subprocess.run


def install_mode(args: argparse.Namespace, env: dict[str, str] | None = None) -> str:
    """How this plugin is permitted to obtain a kernel.

    `auto` manages its own copy, `system` uses only what the operator
    installed and never installs anything, `off` disables the check
    entirely. An unrecognized value falls back to `auto` rather than
    failing: `userConfig` has no enum type, so the value is free text and a
    typo must not break lifecycle governance outright.
    """
    explicit = getattr(args, "mode", None)
    if explicit:
        return explicit
    value = (env or os.environ).get(KERNEL_INSTALL_ENV_VAR, "").strip().lower()
    return value if value in {MODE_AUTO, MODE_SYSTEM, MODE_OFF} else MODE_AUTO


def parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_PATTERN.match(value)
    if not match:
        raise ValueError(f"{value!r} is not MAJOR.MINOR.PATCH semver")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def read_kernel_compatibility(manifest_path: Path | None = None) -> tuple[str, str]:
    """Resolve the supported kernel range, packaged copy first.

    An installed plugin has no repository around it, so the build-emitted
    kernel-compatibility.json beside this script is the only thing present.
    A checkout has no such file and reads the provider manifest directly.
    Passing an explicit path overrides both (used by the tests).
    """
    if manifest_path is None:
        manifest_path = (
            PACKAGED_COMPATIBILITY_PATH
            if PACKAGED_COMPATIBILITY_PATH.is_file()
            else PROVIDER_MANIFEST_PATH
        )
    if not manifest_path.is_file():
        raise SystemExit(
            f"bootstrap-sdlc: no kernel compatibility data at {manifest_path}. "
            "In a checkout this is provider/provider.json; in an installed plugin "
            "it is tools/kernel-compatibility.json, emitted by the plugin build."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # The packaged file *is* the compatibility object; the provider manifest
    # nests it under a key alongside unrelated provider metadata.
    compatibility = manifest.get("kernel_compatibility", manifest)
    if not isinstance(compatibility, dict):
        raise SystemExit(f"bootstrap-sdlc: {manifest_path} has no \"kernel_compatibility\" object")
    minimum = compatibility.get("minimum")
    maximum_exclusive = compatibility.get("maximum_exclusive")
    if not isinstance(minimum, str) or not isinstance(maximum_exclusive, str):
        raise SystemExit(
            f"bootstrap-sdlc: {manifest_path} kernel_compatibility must declare "
            "string \"minimum\" and \"maximum_exclusive\" versions"
        )
    return minimum, maximum_exclusive


def version_in_range(version: str, minimum: str, maximum_exclusive: str) -> bool:
    return parse_semver(minimum) <= parse_semver(version) < parse_semver(maximum_exclusive)


# Deliberately no `resolve_existing_binary()` helper any more: it collapsed
# AGENTIC_SDLC_BIN and a PATH lookup into one answer, which is precisely the
# conflation that made an out-of-range PATH install a dead end. Ownership is
# the thing that decides what may be done with a binary, so ensure_kernel()
# and check() consult the three sources separately and in order.


def binary_version(binary: str) -> str:
    result = _run([binary, "--version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{binary} --version failed: {result.stderr.strip()}")
    return result.stdout.strip()


def managed_root(data_dir: str | None = None, env: dict[str, str] | None = None) -> Path | None:
    """Directory for the plugin-owned kernel, or None if there isn't one.

    `${CLAUDE_PLUGIN_DATA}` is a per-plugin directory that survives plugin
    updates, which is what makes it the right home for an install the plugin
    manages on the user's behalf. A checkout has no such directory, so this
    returns None there and the pipx path is used instead.
    """
    env = os.environ if env is None else env
    base = data_dir or env.get("CLAUDE_PLUGIN_DATA")
    return Path(base) / "kernel" if base else None


def managed_binary(data_dir: str | None = None, env: dict[str, str] | None = None) -> str | None:
    """The plugin-owned `agentic-sdlc`, if it has been created."""
    root = managed_root(data_dir, env)
    if root is None:
        return None
    # `Scripts` on Windows, `bin` everywhere else -- same layout `venv` emits.
    for subdirectory in ("bin", "Scripts"):
        candidate = root / subdirectory / "agentic-sdlc"
        if candidate.is_file():
            return str(candidate)
        candidate = root / subdirectory / "agentic-sdlc.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def venv_install(root: Path, ref: str) -> int:
    """Create (or reuse) a plugin-owned venv and install the kernel into it.

    Uses stdlib `venv` rather than pipx. pipx being absent used to be a hard
    stop -- and even when present it installs into a *shared* bin directory
    that may not be on PATH yet, which is where the "run `pipx ensurepath`,
    start a new shell, re-run" dead end came from. A venv the plugin owns has
    neither problem: nothing outside it is touched, and the plugin's own
    bin/agentic-sdlc shim reaches it without the user's shell profile being
    involved at all.
    """
    print(f"bootstrap-sdlc: installing Agentic SDLC v{ref} into {root}")
    sys.stdout.flush()

    if not root.exists():
        result = _run([sys.executable, "-m", "venv", str(root)], check=False)
        if result.returncode != 0:
            # Debian and Ubuntu ship `ensurepip` in a separate python3-venv
            # package, so stdlib venv creation fails on a stock system Python
            # there. Common enough that it needs its own signal rather than a
            # generic non-zero: ensure_kernel() falls back to pipx, and only
            # if that is missing too does the user see an error -- naming both
            # fixes, since either one resolves it.
            shutil.rmtree(root, ignore_errors=True)
            return VENV_UNAVAILABLE

    for subdirectory in ("bin", "Scripts"):
        pip = root / subdirectory / "pip"
        if pip.is_file() or (root / subdirectory / "pip.exe").is_file():
            break
    else:
        shutil.rmtree(root, ignore_errors=True)
        return VENV_UNAVAILABLE

    # Prefer the published wheel, verified against the release's SHA256SUMS,
    # over the git ref. A tag can be moved; a checksum cannot. Note this
    # pins *the kernel artifact*, not its transitive dependencies -- pip's
    # own --require-hashes would demand a hash for every dependency in the
    # tree, which would mean shipping and maintaining a full lockfile here.
    # Those dependencies come from PyPI exactly as they did before.
    with tempfile.TemporaryDirectory() as scratch:
        pinned = resolve_release_wheel(ref)
        if pinned is None:
            print(
                f"bootstrap-sdlc: no published wheel for {AGENTIC_SDLC_TAG_PREFIX}{ref}; "
                "falling back to the git ref, which cannot be checksum-verified.",
                file=sys.stderr,
            )
            spec = install_target(ref)
        else:
            url, digest = pinned
            try:
                spec = str(download_verified_wheel(url, digest, Path(scratch)))
            except KernelIntegrityError as error:
                # Never silently fall back here: a checksum mismatch is not
                # "this route is unavailable", it is "something is wrong with
                # what was served".
                print(f"bootstrap-sdlc: {error}", file=sys.stderr)
                return 1
            except Exception as error:
                print(
                    f"bootstrap-sdlc: could not download {url} ({error}); "
                    "falling back to the git ref.",
                    file=sys.stderr,
                )
                spec = install_target(ref)

        result = _run(
            [str(pip), "install", "--disable-pip-version-check", spec],
            check=False,
        )
    return result.returncode


def install_target(ref: str) -> str:
    """The git ref to install the kernel from.

    The fallback route, used when a release carries no published wheel (any
    kernel tagged before release.yml started attaching artifacts). A git ref
    cannot be verified after the fact -- a tag can be moved -- and it needs
    `git` plus direct GitHub access, which is the first thing a corporate
    proxy breaks. Prefer `resolve_release_wheel()`.

    Kept as a function so the tag scheme is asserted in one place by
    test_bootstrap_sdlc.py rather than reconstructed at each call site.
    """
    return (
        f"git+{AGENTIC_SDLC_GIT_URL}@{AGENTIC_SDLC_TAG_PREFIX}{ref}#subdirectory={AGENTIC_SDLC_SUBDIRECTORY}"
    )


def release_asset_url(ref: str, filename: str) -> str:
    tag = f"{AGENTIC_SDLC_TAG_PREFIX}{ref}"
    return f"{RELEASE_DOWNLOAD_BASE}/{tag}/{filename}"


def resolve_release_wheel(ref: str, opener=None) -> tuple[str, str] | None:
    """Return (wheel URL, expected sha256) from the release's SHA256SUMS.

    Returns None when the release has no SHA256SUMS or no wheel listed in
    it, so the caller can fall back to the git ref rather than failing --
    kernels tagged before release.yml attached artifacts have neither.
    """
    opener = opener or _urlopen
    try:
        with opener(release_asset_url(ref, "SHA256SUMS"), timeout=NETWORK_TIMEOUT_SECONDS) as handle:
            sums = handle.read().decode("utf-8")
    except Exception:
        # Missing release, no network, proxy, rate limit -- all mean the same
        # thing here: no pinned artifact is available to install.
        return None

    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].endswith(".whl"):
            digest, filename = parts
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return release_asset_url(ref, filename), digest
    return None


def download_verified_wheel(url: str, expected_sha256: str, into: Path, opener=None) -> Path:
    """Download a wheel and refuse to return it unless its hash matches.

    This is the point of the whole exercise: the artifact that gets
    installed is provably the one this project published, rather than
    whatever a mutable tag currently points at.

    The filename is preserved because pip rejects a wheel that has been
    renamed ("not a valid wheel filename") -- it parses the name for the
    distribution, version, and compatibility tags.
    """
    opener = opener or _urlopen
    with opener(url, timeout=NETWORK_TIMEOUT_SECONDS) as handle:
        payload = handle.read()

    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise KernelIntegrityError(
            f"checksum mismatch for {url}\n"
            f"  expected {expected_sha256}\n"
            f"  actual   {actual}\n"
            "Refusing to install. This means the downloaded file is not the artifact "
            "this project published."
        )

    into.mkdir(parents=True, exist_ok=True)
    target = into / url.rsplit("/", 1)[-1]
    target.write_bytes(payload)
    return target


def pipx_install(ref: str) -> int:
    # Same preference as the venv route: a checksum-verified wheel over a
    # movable git ref. pipx has no hash-checking of its own, so the
    # verification happens here and pipx installs the already-verified local
    # file.
    with tempfile.TemporaryDirectory() as scratch:
        pinned = resolve_release_wheel(ref)
        target = install_target(ref)
        if pinned is not None:
            url, digest = pinned
            try:
                target = str(download_verified_wheel(url, digest, Path(scratch)))
            except KernelIntegrityError as error:
                print(f"bootstrap-sdlc: {error}", file=sys.stderr)
                return 1
            except Exception as error:
                print(
                    f"bootstrap-sdlc: could not download {url} ({error}); "
                    "falling back to the git ref.",
                    file=sys.stderr,
                )

        print(f"bootstrap-sdlc: installing Agentic SDLC v{ref} via pipx ({target})")
        # Our own prints above are Python-buffered; pipx's subprocess writes to
        # the same inherited stdout fd directly, so without an explicit flush
        # here its output can appear before ours despite running after it.
        sys.stdout.flush()
        result = _run(["pipx", "install", target], check=False)
    return result.returncode


def build_init_command(
    sdlc_bin: str, args: argparse.Namespace, env: dict[str, str] | None = None
) -> list[str]:
    command = [
        sdlc_bin,
        "--provider",
        str(PROVIDER_MANIFEST_PATH),
        "init",
        "--root",
        str(args.root),
    ]
    # Falls back to the plugin's configured `profile` option so an operator
    # (or a managed-settings fleet) can set it once instead of passing it to
    # every invocation.
    profile = args.profile or (env or os.environ).get(PROFILE_ENV_VAR, "").strip() or None
    if profile is not None:
        command += ["--profile", profile]
    for extension in args.extension:
        command += ["--extension", extension]
    if args.project_id is not None:
        command += ["--project-id", args.project_id]
    if args.classification is not None:
        command += ["--classification", args.classification]
    if args.runner is not None:
        command += ["--runner", args.runner]
    if args.dry_run:
        command += ["--dry-run"]
    return command


def ensure_kernel(args: argparse.Namespace, env: dict[str, str] | None = None) -> tuple[int, str | None]:
    """Resolve, or install, a compatible `agentic-sdlc` binary.

    Returns (exit_code, binary_path). `binary_path` is None whenever no
    further step (init) should run -- either the run failed, or `--dry-run`
    means nothing was actually installed to run against.
    """
    minimum, maximum_exclusive = read_kernel_compatibility()
    data_dir = getattr(args, "data_dir", None)
    mode = install_mode(args, env)

    def in_range(binary: str) -> bool | None:
        """True/False, or None if the binary could not be interrogated."""
        try:
            return version_in_range(binary_version(binary), minimum, maximum_exclusive)
        except (RuntimeError, OSError, ValueError):
            return None

    # --- 1. An install the human chose explicitly always wins. ------------
    explicit = (env or os.environ).get("AGENTIC_SDLC_BIN")
    if explicit:
        verdict = in_range(explicit)
        if verdict:
            print(f"bootstrap-sdlc: using AGENTIC_SDLC_BIN ({explicit})")
            return 0, explicit
        if verdict is None:
            print(f"bootstrap-sdlc: could not run AGENTIC_SDLC_BIN ({explicit})", file=sys.stderr)
            return 1, None
        # Fail closed, exactly as before: the human named this binary, so
        # silently substituting a different one would be the wrong answer.
        print(
            f"bootstrap-sdlc: AGENTIC_SDLC_BIN points at {explicit}, which is outside this "
            f"plugin's supported range [{minimum}, {maximum_exclusive}). Point it at a "
            "compatible install, or unset it to let this plugin manage its own copy.",
            file=sys.stderr,
        )
        return 1, None

    # --- 2. The plugin-owned copy, which the plugin may freely manage. ----
    managed = managed_binary(data_dir, env)
    if managed and in_range(managed):
        print(f"bootstrap-sdlc: using this plugin's managed kernel ({managed})")
        return 0, managed

    # --- 3. Whatever the operator installed themselves. -------------------
    #
    # Out-of-range here used to be a hard stop with no way forward except
    # uninstalling your own tool. It is now a fallback to the managed copy:
    # the operator's install is left untouched (this plugin never chose it),
    # and the plugin uses something it owns instead.
    on_path = shutil.which("agentic-sdlc")
    outranged: str | None = None
    if on_path:
        verdict = in_range(on_path)
        if verdict:
            print(f"bootstrap-sdlc: Agentic SDLC already installed and compatible ({on_path})")
            return 0, on_path
        if verdict is False:
            outranged = on_path

    if mode in {MODE_SYSTEM, MODE_OFF}:
        print(
            f"bootstrap-sdlc: kernelInstall={mode}, so nothing will be installed. Provide a "
            f"kernel in [{minimum}, {maximum_exclusive}) on PATH or via AGENTIC_SDLC_BIN.",
            file=sys.stderr,
        )
        return 1, None

    root = managed_root(data_dir, env)

    # Printed before the dry-run branch: "there is an install here that I am
    # deliberately not using" is exactly the kind of thing a dry run exists
    # to surface.
    if outranged:
        print(
            f"bootstrap-sdlc: {outranged} is outside the supported range "
            f"[{minimum}, {maximum_exclusive}); leaving it alone and using a copy this plugin "
            "manages instead."
        )

    if args.dry_run:
        where = f"a managed venv at {root}" if root else "pipx"
        print(f"bootstrap-sdlc: would install {install_target(minimum)} into {where}")
        return 0, None

    # --- 4. Install. Prefer the plugin-owned venv; pipx is the fallback. --
    if root is not None:
        returncode = venv_install(root, minimum)
        if returncode == 0:
            installed = managed_binary(data_dir, env)
            if not installed:
                print(
                    f"bootstrap-sdlc: install reported success but no agentic-sdlc appeared in {root}",
                    file=sys.stderr,
                )
                return 1, None
            return 0, installed
        if returncode != VENV_UNAVAILABLE:
            return returncode, None
        print(
            "bootstrap-sdlc: this Python cannot create a virtualenv (Debian and Ubuntu "
            "ship `ensurepip` in a separate python3-venv package); trying pipx instead.",
            file=sys.stderr,
        )

    if shutil.which("pipx") is None:
        print(
            "bootstrap-sdlc: could not install the kernel. Either install the venv module "
            "for this Python (e.g. `apt install python3-venv`) and re-run, or install pipx "
            "(https://pipx.pypa.io/stable/installation/), or install Agentic SDLC yourself "
            "and set AGENTIC_SDLC_BIN.",
            file=sys.stderr,
        )
        return 1, None

    returncode = pipx_install(minimum)
    if returncode != 0:
        return returncode, None

    installed = shutil.which("agentic-sdlc")
    if not installed:
        print(
            "bootstrap-sdlc: pipx install succeeded, but agentic-sdlc still isn't resolvable on "
            "PATH in this shell. Run `pipx ensurepath`, start a new shell, and re-run this "
            "command to finish configuring the project.",
            file=sys.stderr,
        )
        return 1, None
    return 0, installed


def check(args: argparse.Namespace, env: dict[str, str] | None = None) -> int:
    """Report kernel availability without installing or writing anything.

    This is what the `SessionStart` hook calls, and the constraints come from
    that: it must never install (a hook that runs `pip install` from a
    network URL before the user has done anything is a supply-chain
    objection, not a convenience), never mutate anything, and never fail --
    a non-zero exit or a stall here degrades every session start for a
    problem that is at worst "one optional feature is not set up yet".

    Prints nothing at all when a compatible kernel is already resolvable, so
    the common case is silent.
    """
    mode = install_mode(args, env)
    if mode == MODE_OFF:
        # The operator turned this off deliberately. Saying so every session
        # would just be nagging about a decision already made.
        return 0

    try:
        minimum, maximum_exclusive = read_kernel_compatibility()
    except SystemExit:
        return 0

    data_dir = getattr(args, "data_dir", None)
    environment = env or os.environ

    for binary in (
        environment.get("AGENTIC_SDLC_BIN"),
        managed_binary(data_dir, env),
        shutil.which("agentic-sdlc"),
    ):
        if not binary:
            continue
        try:
            if version_in_range(binary_version(binary), minimum, maximum_exclusive):
                return 0
        except (RuntimeError, OSError, ValueError):
            continue

    if mode == MODE_SYSTEM:
        # Offering to install would contradict the configured mode.
        print(
            "Lifecycle governance needs the Agentic SDLC kernel "
            f"(v{minimum} or newer, below v{maximum_exclusive}). This plugin is configured "
            "with kernelInstall=system, so install one yourself and put it on PATH or set "
            "AGENTIC_SDLC_BIN."
        )
        return 0

    print(
        "Lifecycle governance needs the Agentic SDLC kernel "
        f"(v{minimum} or newer, below v{maximum_exclusive}), which is not set up yet.\n"
        "Run the /cadre-install-kernel skill, or `cadre-install-kernel`, to install it.\n"
        "It installs into this plugin's own data directory and changes nothing else."
    )
    return 0


def bootstrap(args: argparse.Namespace, env: dict[str, str] | None = None) -> int:
    if getattr(args, "check", False):
        return check(args, env)

    exit_code, sdlc_bin = ensure_kernel(args, env)
    if exit_code != 0:
        return exit_code

    if args.skip_init:
        return 0

    if sdlc_bin is None:
        # Either --dry-run (nothing to configure against yet) or the kernel
        # was just installed but isn't resolvable in this process -- either
        # way ensure_kernel() already reported the reason.
        return 0

    sys.stdout.flush()
    result = _run(build_init_command(sdlc_bin, args, env), check=False)
    return result.returncode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target project root (default: cwd)")
    parser.add_argument("--profile", help="Provider profile id; omit for kernel-only lifecycle operation")
    parser.add_argument("--extension", action="append", default=[], help="Enable an impact-profile extension by id (repeatable)")
    parser.add_argument("--project-id")
    parser.add_argument("--classification")
    parser.add_argument("--runner", choices=["codex", "claude", "both"])
    parser.add_argument(
        "--data-dir",
        help=(
            "Directory for the kernel copy this plugin manages. Defaults to "
            "$CLAUDE_PLUGIN_DATA, which Claude Code sets per plugin and preserves "
            "across plugin updates. Without either, installation falls back to pipx."
        ),
    )
    parser.add_argument("--skip-init", action="store_true", help="Install/verify the kernel only; do not configure a project")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without installing or writing anything")
    parser.add_argument(
        "--mode",
        choices=[MODE_AUTO, MODE_SYSTEM, MODE_OFF],
        help=(
            "Override the plugin's kernelInstall option for this run. Normally read "
            "from the CLAUDE_PLUGIN_OPTION_KERNELINSTALL environment variable."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Detect and report only: never installs, never writes, always exits 0. "
            "Silent when a compatible kernel is already resolvable. This is what the "
            "SessionStart hook runs."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return bootstrap(args)


if __name__ == "__main__":
    raise SystemExit(main())
