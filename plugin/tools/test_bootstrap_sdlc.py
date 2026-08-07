#!/usr/bin/env python3
"""Tests for plugin/tools/bootstrap_sdlc.py.

Covers the decision logic around whether to install, reuse, or refuse an
existing `agentic-sdlc` binary, and that the `init` command it builds matches
what `bin/cadre sdlc` itself would invoke. Subprocess calls (`pipx`,
`agentic-sdlc --version`, `agentic-sdlc init`) are stubbed via
`bootstrap_sdlc._run` so these tests never touch the network or a real
install.

    python3 -m unittest discover -s plugin/tools -p "test_*.py"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bootstrap_sdlc  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        root=Path("/tmp/project"),
        profile=None,
        extension=[],
        project_id=None,
        classification=None,
        runner=None,
        skip_init=False,
        dry_run=False,
        data_dir=None,
        check=False,
        mode=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class VersionRangeTests(unittest.TestCase):
    def test_minimum_is_inclusive(self) -> None:
        self.assertTrue(bootstrap_sdlc.version_in_range("0.3.0", "0.3.0", "0.4.0"))

    def test_maximum_is_exclusive(self) -> None:
        self.assertFalse(bootstrap_sdlc.version_in_range("0.4.0", "0.3.0", "0.4.0"))

    def test_below_minimum_is_out_of_range(self) -> None:
        self.assertFalse(bootstrap_sdlc.version_in_range("0.2.9", "0.3.0", "0.4.0"))

    def test_invalid_semver_raises(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_sdlc.parse_semver("v0.3.0")


class ReadKernelCompatibilityTests(unittest.TestCase):
    def test_reads_minimum_and_maximum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "provider.json"
            manifest.write_text(
                json.dumps({"kernel_compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"}}),
                encoding="utf-8",
            )
            self.assertEqual(("0.3.0", "0.4.0"), bootstrap_sdlc.read_kernel_compatibility(manifest))

    def test_missing_manifest_exits(self) -> None:
        with self.assertRaises(SystemExit):
            bootstrap_sdlc.read_kernel_compatibility(Path("/nonexistent/provider.json"))

    def test_this_repositorys_own_manifest_is_readable(self) -> None:
        minimum, maximum_exclusive = bootstrap_sdlc.read_kernel_compatibility()
        self.assertRegex(minimum, r"^\d+\.\d+\.\d+$")
        self.assertRegex(maximum_exclusive, r"^\d+\.\d+\.\d+$")


class EnsureKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._compat_patch = mock.patch.object(
            bootstrap_sdlc, "read_kernel_compatibility", return_value=("0.3.0", "0.4.0")
        )
        self._compat_patch.start()
        self.addCleanup(self._compat_patch.stop)

    @staticmethod
    def _which(mapping: dict[str, str | None]):
        """`shutil.which` is now consulted for more than one name, so the
        stub has to answer per-name rather than returning one value."""
        return mock.patch.object(
            bootstrap_sdlc.shutil, "which", side_effect=lambda name: mapping.get(name)
        )

    def test_compatible_existing_binary_is_reused_without_reinstalling(self) -> None:
        with self._which({"agentic-sdlc": "/usr/local/bin/agentic-sdlc"}), \
             mock.patch.object(bootstrap_sdlc, "binary_version", return_value="0.3.0"), \
             mock.patch.object(bootstrap_sdlc, "pipx_install") as install:
            exit_code, binary = bootstrap_sdlc.ensure_kernel(_args(), {})
        install.assert_not_called()
        self.assertEqual(0, exit_code)
        self.assertEqual("/usr/local/bin/agentic-sdlc", binary)

    def test_incompatible_binary_on_path_is_left_alone_and_superseded(self) -> None:
        """Behaviour change, deliberate. This used to exit 1 with "not
        reinstalling automatically", which left the user with a broken plugin
        and no way forward except uninstalling their own tool. The operator's
        install is still never modified -- it is simply not used."""
        with self._which({"agentic-sdlc": "/usr/local/bin/agentic-sdlc", "pipx": "/usr/bin/pipx"}), \
             mock.patch.object(bootstrap_sdlc, "binary_version", return_value="0.9.0"), \
             mock.patch.object(bootstrap_sdlc, "pipx_install", return_value=0) as install:
            exit_code, _binary = bootstrap_sdlc.ensure_kernel(_args(), {})
        self.assertEqual(0, exit_code)
        install.assert_called_once_with("0.3.0")

    def test_no_install_route_at_all_fails_closed(self) -> None:
        with self._which({}), mock.patch("sys.stderr"):
            exit_code, binary = bootstrap_sdlc.ensure_kernel(_args(), {})
        self.assertEqual(1, exit_code)
        self.assertIsNone(binary)

    def test_dry_run_never_installs(self) -> None:
        with self._which({"pipx": "/usr/bin/pipx"}), \
             mock.patch.object(bootstrap_sdlc, "pipx_install") as install:
            exit_code, binary = bootstrap_sdlc.ensure_kernel(_args(dry_run=True), {})
        install.assert_not_called()
        self.assertEqual(0, exit_code)
        self.assertIsNone(binary)

    def test_pinned_install_uses_the_declared_minimum_version(self) -> None:
        # Absent before the install, present after -- the post-install lookup
        # is what turns a successful install into a usable binary path.
        resolved = {"pipx": "/usr/bin/pipx", "agentic-sdlc": None}

        def installed(_ref):
            resolved["agentic-sdlc"] = "/usr/local/bin/agentic-sdlc"
            return 0

        with mock.patch.object(
            bootstrap_sdlc.shutil, "which", side_effect=lambda name: resolved.get(name)
        ), mock.patch.object(bootstrap_sdlc, "pipx_install", side_effect=installed) as install:
            exit_code, binary = bootstrap_sdlc.ensure_kernel(_args(), {})
        install.assert_called_once_with("0.3.0")
        self.assertEqual(0, exit_code)
        self.assertEqual("/usr/local/bin/agentic-sdlc", binary)

    def test_install_success_but_still_unresolvable_reports_path_guidance(self) -> None:
        with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value=None):
                with mock.patch.object(bootstrap_sdlc, "pipx_install", return_value=0):
                    exit_code, binary = bootstrap_sdlc.ensure_kernel(_args())
        self.assertEqual(1, exit_code)
        self.assertIsNone(binary)


class BuildInitCommandTests(unittest.TestCase):
    def test_minimal_command_matches_bin_cadre_sdlc_provider_flag(self) -> None:
        command = bootstrap_sdlc.build_init_command("/usr/local/bin/agentic-sdlc", _args(root=Path("/proj")))
        self.assertEqual(
            [
                "/usr/local/bin/agentic-sdlc",
                "--provider",
                str(bootstrap_sdlc.PROVIDER_MANIFEST_PATH),
                "init",
                "--root",
                "/proj",
            ],
            command,
        )

    def test_optional_flags_are_passed_through(self) -> None:
        command = bootstrap_sdlc.build_init_command(
            "agentic-sdlc",
            _args(
                root=Path("/proj"),
                profile="secure-cloud",
                extension=["a", "b"],
                project_id="proj-1",
                classification="internal",
                runner="both",
                dry_run=True,
            ),
        )
        self.assertIn("--profile", command)
        self.assertEqual("secure-cloud", command[command.index("--profile") + 1])
        self.assertEqual(2, command.count("--extension"))
        self.assertIn("proj-1", command)
        self.assertIn("internal", command)
        self.assertIn("both", command)
        self.assertIn("--dry-run", command)


class BootstrapTests(unittest.TestCase):
    def test_skip_init_stops_before_running_init(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "ensure_kernel", return_value=(0, "/usr/local/bin/agentic-sdlc")):
            with mock.patch.object(bootstrap_sdlc, "_run") as run:
                exit_code = bootstrap_sdlc.bootstrap(_args(skip_init=True))
        run.assert_not_called()
        self.assertEqual(0, exit_code)

    def test_kernel_failure_short_circuits_before_init(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "ensure_kernel", return_value=(1, None)):
            with mock.patch.object(bootstrap_sdlc, "_run") as run:
                exit_code = bootstrap_sdlc.bootstrap(_args())
        run.assert_not_called()
        self.assertEqual(1, exit_code)

    def test_successful_kernel_resolution_runs_init(self) -> None:
        completed = mock.Mock(returncode=0)
        with mock.patch.object(bootstrap_sdlc, "ensure_kernel", return_value=(0, "/usr/local/bin/agentic-sdlc")):
            with mock.patch.object(bootstrap_sdlc, "_run", return_value=completed) as run:
                exit_code = bootstrap_sdlc.bootstrap(_args())
        run.assert_called_once()
        self.assertEqual(0, exit_code)


if __name__ == "__main__":
    unittest.main()


class InstallTargetTests(unittest.TestCase):
    """The kernel install ref. Untested until it broke in production.

    `bootstrap_sdlc.py` installed `@v{version}#subdirectory=kernel` from
    deagy/cadre after the monorepo merge. That tag *exists* -- the monorepo
    inherited 25 bare `v*` tags from the pre-merge deagy/cadre -- but it
    points at old-cadre history with no kernel/ directory, so pip resolved a
    real ref and then found nothing to install. Nothing here asserted the
    ref, so nothing caught it.
    """

    def test_target_uses_the_component_prefixed_tag(self) -> None:
        target = bootstrap_sdlc.install_target("0.13.0")
        self.assertIn("@kernel-v0.13.0#", target)
        self.assertIn("subdirectory=kernel", target)
        self.assertTrue(target.startswith("git+https://github.com/deagy/cadre.git@"))

    def test_target_never_uses_a_bare_version_tag(self) -> None:
        """`@v0.13.0` collides with inherited pre-merge tags."""
        target = bootstrap_sdlc.install_target("0.13.0")
        self.assertNotIn("@v0.13.0", target)
        self.assertNotIn(".git@v", target)

    def test_dry_run_reports_the_same_target_it_would_install(self) -> None:
        """A --dry-run that prints a different ref than it installs is worse
        than no dry run at all."""
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "provider.json"
            manifest.write_text(
                json.dumps({"kernel_compatibility": {"minimum": "0.13.0",
                                                     "maximum_exclusive": "1.0.0"}}),
                encoding="utf-8",
            )
            with mock.patch.object(bootstrap_sdlc, "PROVIDER_MANIFEST_PATH", manifest), \
                 mock.patch.object(bootstrap_sdlc, "PACKAGED_COMPATIBILITY_PATH",
                                   Path(directory) / "absent.json"), \
                 mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/pipx"), \
                 mock.patch("sys.stdout") as stdout:
                code, binary = bootstrap_sdlc.ensure_kernel(_args(dry_run=True))

        self.assertEqual(0, code)
        self.assertIsNone(binary)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list if call.args)
        self.assertIn(bootstrap_sdlc.install_target("0.13.0"), printed)


def _compat(directory: str) -> Path:
    manifest = Path(directory) / "provider.json"
    manifest.write_text(
        json.dumps({"kernel_compatibility": {"minimum": "0.13.0", "maximum_exclusive": "1.0.0"}}),
        encoding="utf-8",
    )
    return manifest


class OwnershipTests(unittest.TestCase):
    """Who owns an install decides whether this script may act on it.

    The pre-merge rule was one-size: never touch an existing install, even an
    incompatible one. That was right for a binary the human chose and wrong
    for everything else -- an out-of-range `agentic-sdlc` on PATH left the
    user with a broken plugin and no way forward except uninstalling their
    own tool.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manifest = _compat(self.directory.name)
        patcher = mock.patch.object(bootstrap_sdlc, "PROVIDER_MANIFEST_PATH", self.manifest)
        patcher.start()
        self.addCleanup(patcher.stop)
        absent = mock.patch.object(
            bootstrap_sdlc, "PACKAGED_COMPATIBILITY_PATH", Path(self.directory.name) / "absent.json"
        )
        absent.start()
        self.addCleanup(absent.stop)

    def _versions(self, mapping: dict[str, str]):
        return mock.patch.object(bootstrap_sdlc, "binary_version", lambda b: mapping[b])

    def test_explicit_bin_out_of_range_still_fails_closed(self) -> None:
        """The human named this binary. Substituting another silently would
        be the wrong answer, so this remains a hard stop."""
        env = {"AGENTIC_SDLC_BIN": "/opt/mine/agentic-sdlc"}
        with self._versions({"/opt/mine/agentic-sdlc": "0.9.0"}):
            code, binary = bootstrap_sdlc.ensure_kernel(_args(dry_run=True), env)
        self.assertEqual(1, code)
        self.assertIsNone(binary)

    def test_explicit_bin_in_range_wins_over_everything(self) -> None:
        env = {"AGENTIC_SDLC_BIN": "/opt/mine/agentic-sdlc"}
        with self._versions({"/opt/mine/agentic-sdlc": "0.13.0"}):
            code, binary = bootstrap_sdlc.ensure_kernel(_args(), env)
        self.assertEqual(0, code)
        self.assertEqual("/opt/mine/agentic-sdlc", binary)

    def test_managed_copy_is_preferred_over_path(self) -> None:
        data = Path(self.directory.name) / "data"
        managed = data / "kernel" / "bin" / "agentic-sdlc"
        managed.parent.mkdir(parents=True)
        managed.write_text("#!/bin/sh\n", encoding="utf-8")
        with self._versions({str(managed): "0.13.0", "/usr/bin/agentic-sdlc": "0.13.0"}), \
             mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/agentic-sdlc"):
            code, binary = bootstrap_sdlc.ensure_kernel(_args(data_dir=str(data)), {})
        self.assertEqual(0, code)
        self.assertEqual(str(managed), binary)

    def test_out_of_range_path_install_is_left_alone_not_a_dead_end(self) -> None:
        """The regression this whole split exists to prevent."""
        data = Path(self.directory.name) / "data"
        with self._versions({"/usr/bin/agentic-sdlc": "0.9.0"}), \
             mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/agentic-sdlc"), \
             mock.patch("sys.stdout") as stdout:
            code, _binary = bootstrap_sdlc.ensure_kernel(
                _args(dry_run=True, data_dir=str(data)), {}
            )
        self.assertEqual(0, code, "an out-of-range PATH install must not be a hard stop")
        printed = "".join(c.args[0] for c in stdout.write.call_args_list if c.args)
        self.assertIn("leaving it alone", printed)


class VenvFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_venv_creation_failure_is_distinguishable_from_a_pip_failure(self) -> None:
        """Debian and Ubuntu ship ensurepip separately, so venv creation
        failing is an ordinary environment, not a bug -- and it must route to
        the pipx fallback rather than aborting."""
        root = Path(self.directory.name) / "kernel"
        with mock.patch.object(
            bootstrap_sdlc, "_run",
            return_value=subprocess.CompletedProcess([], 1, "", "ensurepip is not available"),
        ):
            code = bootstrap_sdlc.venv_install(root, "0.13.0")
        self.assertEqual(bootstrap_sdlc.VENV_UNAVAILABLE, code)
        self.assertFalse(root.exists(), "a half-built venv must not be left behind")


class CheckModeTests(unittest.TestCase):
    """`--check` is what the SessionStart hook runs, so its contract is
    narrow: never install, never write, never fail, and stay silent when
    there is nothing to say."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manifest = _compat(self.directory.name)
        for name, value in (
            ("PROVIDER_MANIFEST_PATH", self.manifest),
            ("PACKAGED_COMPATIBILITY_PATH", Path(self.directory.name) / "absent.json"),
        ):
            patcher = mock.patch.object(bootstrap_sdlc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_silent_and_zero_when_a_compatible_kernel_exists(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "binary_version", lambda b: "0.13.0"), \
             mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/agentic-sdlc"), \
             mock.patch("sys.stdout") as stdout:
            code = bootstrap_sdlc.check(_args(check=True), {})
        self.assertEqual(0, code)
        self.assertEqual("", "".join(c.args[0] for c in stdout.write.call_args_list if c.args))

    def test_reports_and_still_exits_zero_when_missing(self) -> None:
        with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value=None), \
             mock.patch("sys.stdout") as stdout:
            code = bootstrap_sdlc.check(_args(check=True), {})
        printed = "".join(c.args[0] for c in stdout.write.call_args_list if c.args)
        self.assertEqual(0, code, "a hook must never fail a session start")
        self.assertIn("cadre-install-kernel", printed)

    def test_check_never_installs(self) -> None:
        with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value=None), \
             mock.patch.object(bootstrap_sdlc, "_run") as run, \
             mock.patch.object(bootstrap_sdlc, "venv_install") as install, \
             mock.patch("sys.stdout"):
            bootstrap_sdlc.check(_args(check=True), {})
        install.assert_not_called()
        run.assert_not_called()


class InstallModeTests(unittest.TestCase):
    """`kernelInstall` reaches this script as CLAUDE_PLUGIN_OPTION_KERNELINSTALL.

    Shell-form hook commands cannot substitute `${user_config.*}` -- Claude
    Code rejects it, because interpolating a configured value into a shell
    command would let the shell execute whatever it contains -- so the
    environment variable is the supported route, not a workaround.
    """

    def test_unset_defaults_to_auto(self) -> None:
        self.assertEqual("auto", bootstrap_sdlc.install_mode(_args(), {}))

    def test_unrecognized_value_falls_back_to_auto(self) -> None:
        """`userConfig` has no enum type, so this is free text. A typo must
        not disable lifecycle governance outright."""
        env = {"CLAUDE_PLUGIN_OPTION_KERNELINSTALL": "atuo"}
        self.assertEqual("auto", bootstrap_sdlc.install_mode(_args(), env))

    def test_each_documented_value_is_honoured(self) -> None:
        for value in ("auto", "system", "off"):
            with self.subTest(value=value):
                env = {"CLAUDE_PLUGIN_OPTION_KERNELINSTALL": value.upper() + " "}
                self.assertEqual(value, bootstrap_sdlc.install_mode(_args(), env))

    def test_explicit_flag_overrides_the_environment(self) -> None:
        env = {"CLAUDE_PLUGIN_OPTION_KERNELINSTALL": "off"}
        self.assertEqual("system", bootstrap_sdlc.install_mode(_args(mode="system"), env))

    def test_off_makes_check_completely_silent(self) -> None:
        env = {"CLAUDE_PLUGIN_OPTION_KERNELINSTALL": "off"}
        with mock.patch("sys.stdout") as stdout:
            code = bootstrap_sdlc.check(_args(check=True), env)
        self.assertEqual(0, code)
        self.assertEqual("", "".join(c.args[0] for c in stdout.write.call_args_list if c.args))

    def test_system_and_off_never_install(self) -> None:
        for value in ("system", "off"):
            env = {"CLAUDE_PLUGIN_OPTION_KERNELINSTALL": value}
            with self.subTest(mode=value), \
                 mock.patch.object(bootstrap_sdlc, "read_kernel_compatibility",
                                   return_value=("0.13.0", "1.0.0")), \
                 mock.patch.object(bootstrap_sdlc.shutil, "which", return_value=None), \
                 mock.patch.object(bootstrap_sdlc, "venv_install") as venv, \
                 mock.patch.object(bootstrap_sdlc, "pipx_install") as pipx, \
                 mock.patch("sys.stderr"):
                code, binary = bootstrap_sdlc.ensure_kernel(_args(), env)
            venv.assert_not_called()
            pipx.assert_not_called()
            self.assertEqual(1, code)
            self.assertIsNone(binary)


class ProfileOptionTests(unittest.TestCase):
    def test_configured_profile_is_used_when_none_is_passed(self) -> None:
        env = {"CLAUDE_PLUGIN_OPTION_PROFILE": "secure-cloud"}
        command = bootstrap_sdlc.build_init_command("/bin/agentic-sdlc", _args(profile=None), env)
        self.assertIn("--profile", command)
        self.assertEqual("secure-cloud", command[command.index("--profile") + 1])

    def test_explicit_profile_wins_over_the_configured_one(self) -> None:
        env = {"CLAUDE_PLUGIN_OPTION_PROFILE": "secure-cloud"}
        command = bootstrap_sdlc.build_init_command("/bin/agentic-sdlc", _args(profile="generic"), env)
        self.assertEqual("generic", command[command.index("--profile") + 1])

    def test_blank_configured_profile_is_treated_as_unset(self) -> None:
        command = bootstrap_sdlc.build_init_command(
            "/bin/agentic-sdlc", _args(profile=None), {"CLAUDE_PLUGIN_OPTION_PROFILE": "   "}
        )
        self.assertNotIn("--profile", command)
