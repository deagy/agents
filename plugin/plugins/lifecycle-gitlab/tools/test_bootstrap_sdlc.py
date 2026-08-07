#!/usr/bin/env python3
"""Tests for plugins/lifecycle-gitlab/tools/bootstrap_sdlc.py.

Covers the decision logic around whether to install, reuse, or refuse an
existing `agentic-sdlc` binary, and that the `init` command it builds matches
what `bin/cadre sdlc` itself would invoke. Subprocess calls (`pipx`,
`agentic-sdlc --version`, `agentic-sdlc init`) are stubbed via
`bootstrap_sdlc._run` so these tests never touch the network or a real
install.

    python3 -m unittest discover -s plugins/lifecycle-gitlab/tools -p "test_*.py"
"""

from __future__ import annotations

import argparse
import json
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

    def test_compatible_existing_binary_is_reused_without_reinstalling(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", return_value="/usr/local/bin/agentic-sdlc"):
            with mock.patch.object(bootstrap_sdlc, "binary_version", return_value="0.3.0"):
                with mock.patch.object(bootstrap_sdlc, "pipx_install") as install:
                    exit_code, binary = bootstrap_sdlc.ensure_kernel(_args())
        install.assert_not_called()
        self.assertEqual(0, exit_code)
        self.assertEqual("/usr/local/bin/agentic-sdlc", binary)

    def test_incompatible_existing_binary_is_refused_not_replaced(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", return_value="/usr/local/bin/agentic-sdlc"):
            with mock.patch.object(bootstrap_sdlc, "binary_version", return_value="0.9.0"):
                with mock.patch.object(bootstrap_sdlc, "pipx_install") as install:
                    exit_code, binary = bootstrap_sdlc.ensure_kernel(_args())
        install.assert_not_called()
        self.assertEqual(1, exit_code)
        self.assertIsNone(binary)

    def test_missing_pipx_fails_closed(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", return_value=None):
            with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value=None):
                exit_code, binary = bootstrap_sdlc.ensure_kernel(_args())
        self.assertEqual(1, exit_code)
        self.assertIsNone(binary)

    def test_dry_run_never_installs(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", return_value=None):
            with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/pipx"):
                with mock.patch.object(bootstrap_sdlc, "pipx_install") as install:
                    exit_code, binary = bootstrap_sdlc.ensure_kernel(_args(dry_run=True))
        install.assert_not_called()
        self.assertEqual(0, exit_code)
        self.assertIsNone(binary)

    def test_pinned_install_uses_the_declared_minimum_version(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", side_effect=[None, "/usr/local/bin/agentic-sdlc"]):
            with mock.patch.object(bootstrap_sdlc.shutil, "which", return_value="/usr/bin/pipx"):
                with mock.patch.object(bootstrap_sdlc, "pipx_install", return_value=0) as install:
                    exit_code, binary = bootstrap_sdlc.ensure_kernel(_args())
        install.assert_called_once_with("0.3.0")
        self.assertEqual(0, exit_code)
        self.assertEqual("/usr/local/bin/agentic-sdlc", binary)

    def test_install_success_but_still_unresolvable_reports_path_guidance(self) -> None:
        with mock.patch.object(bootstrap_sdlc, "resolve_existing_binary", return_value=None):
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
