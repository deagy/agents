#!/usr/bin/env python3
"""Guards on install.sh and install.ps1.

These scripts are the first thing a new user runs and the least likely thing
to be exercised in normal development, so the properties worth pinning are
the ones whose failure is silent or destructive:

* **Coordinates match reality.** A marketplace or plugin name that drifts
  from `.claude-plugin/marketplace.json` produces an installer that fails at
  the last step, after already having changed things.
* **`--uninstall` honours `--runner`.** It did not, and
  `--runner=codex --uninstall` removed a working Claude Code install. That
  is the worst thing either script can do.
* **No hardcoded version tag.** Same class of bug as the pinned marketplace
  refs Phase 1 removed.
* **The two scripts agree.** They are separate implementations of one
  behaviour; nothing but a test keeps them aligned.

    python3 -m unittest discover -s plugin/tools -p "test_*.py"
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SH = REPO_ROOT / "install.sh"
PS1 = REPO_ROOT / "install.ps1"
CLAUDE_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"


class TestInstallersExist(unittest.TestCase):
    def test_both_scripts_are_present(self) -> None:
        self.assertTrue(SH.is_file(), str(SH))
        self.assertTrue(PS1.is_file(), str(PS1))

    def test_posix_installer_is_executable(self) -> None:
        self.assertTrue(SH.stat().st_mode & 0o111, "install.sh must be executable")

    def test_posix_installer_is_sh_not_bash(self) -> None:
        """It runs on machines nobody has prepared; bashisms defeat that."""
        self.assertTrue(SH.read_text(encoding="utf-8").startswith("#!/bin/sh"))


class TestCoordinatesMatchTheMarketplaces(unittest.TestCase):
    def setUp(self) -> None:
        self.claude = json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))
        self.codex = json.loads(CODEX_MARKETPLACE.read_text(encoding="utf-8"))
        self.sh = SH.read_text(encoding="utf-8")
        self.ps1 = PS1.read_text(encoding="utf-8")

    def test_both_marketplaces_agree_on_their_name(self) -> None:
        """Claude and Codex read different manifest paths. If they disagree
        on the marketplace name, one runner's install silently targets a
        marketplace that does not exist."""
        self.assertEqual(self.claude["name"], self.codex["name"])

    def test_installers_use_that_marketplace_name(self) -> None:
        name = self.claude["name"]
        self.assertIn(f'MARKETPLACE="{name}"', self.sh)
        self.assertIn(f"$Marketplace = '{name}'", self.ps1)

    def test_installers_use_a_plugin_the_marketplace_actually_declares(self) -> None:
        declared = {entry["name"] for entry in self.claude["plugins"]}
        self.assertIn("cadre", declared)
        self.assertIn('PLUGIN="cadre"', self.sh)
        # The optional lifecycle plugin both scripts install with
        # --with-lifecycle must exist too.
        self.assertIn("cadre-lifecycle-core", declared)
        self.assertIn("cadre-lifecycle-core", self.sh)
        self.assertIn("cadre-lifecycle-core", self.ps1)

    def test_codex_marketplace_paths_resolve(self) -> None:
        """Codex reads its manifest from the repository root, so every source
        path needs the plugin/ prefix the monorepo introduced. A stale ./
        path silently resolves to the repo root instead of the plugin."""
        for entry in self.codex["plugins"]:
            path = entry["source"]["path"]
            with self.subTest(plugin=entry["name"]):
                self.assertTrue(path.startswith("./plugin"), path)
                self.assertTrue((REPO_ROOT / path).is_dir(), path)


class TestNoHardcodedVersions(unittest.TestCase):
    PINNED = re.compile(r"@v\d+\.\d+\.\d+|--branch\s+v\d|clone\s+--branch")

    def test_neither_installer_pins_a_release_tag(self) -> None:
        for path in (SH, PS1):
            with self.subTest(script=path.name):
                self.assertIsNone(
                    self.PINNED.search(path.read_text(encoding="utf-8")),
                    "installers must track the default branch; a written-down tag goes stale",
                )


class TestUninstallHonoursRunnerScope(unittest.TestCase):
    """`--runner=codex --uninstall` once removed a working Claude Code
    install, because uninstall looped over every *detected* runner instead of
    the requested ones. Removing something the operator did not ask to remove
    is the worst failure mode either script has."""

    def test_posix_uninstall_iterates_the_requested_runners(self) -> None:
        body = SH.read_text(encoding="utf-8")
        section = body[body.index("do_uninstall()"):]
        self.assertIn('targets="$RUNNERS"', section)
        self.assertNotIn("for runner in $(detect_runners); do", section)

    def test_posix_scoped_uninstall_keeps_shared_artifacts(self) -> None:
        """The checkout and launcher are shared, so a scoped uninstall must
        not delete them out from under the runners left installed."""
        body = SH.read_text(encoding="utf-8")
        section = body[body.index("do_uninstall()"):]
        self.assertIn('if [ "$scoped" -eq 1 ]', section)

    def test_powershell_uninstall_is_scoped_the_same_way(self) -> None:
        body = PS1.read_text(encoding="utf-8")
        self.assertIn("Invoke-Uninstall -Targets $targets -Scoped:$scoped", body)
        self.assertIn("if ($Scoped)", body)


class TestBothScriptsOfferTheSameContract(unittest.TestCase):
    def test_same_switches(self) -> None:
        sh, ps1 = SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")
        for posix, powershell in (
            ("--dry-run", "$DryRun"),
            ("--uninstall", "$Uninstall"),
            ("--with-lifecycle", "$WithLifecycle"),
            ("--runner=", "$Runner"),
        ):
            with self.subTest(option=posix):
                self.assertIn(posix, sh)
                self.assertIn(powershell, ps1)

    def test_both_back_up_the_codex_config_before_editing_it(self) -> None:
        """It is a file the operator owns and may have edited by hand."""
        self.assertIn("cadre-backup", SH.read_text(encoding="utf-8"))
        self.assertIn("cadre-backup", PS1.read_text(encoding="utf-8"))

    def test_both_use_a_fenced_block_so_reruns_do_not_duplicate(self) -> None:
        for path in (SH, PS1):
            body = path.read_text(encoding="utf-8")
            with self.subTest(script=path.name):
                self.assertIn(">>> cadre >>>", body)
                self.assertIn("<<< cadre <<<", body)

    def test_both_refresh_the_codex_marketplace_snapshot(self) -> None:
        """`codex plugin marketplace add` is a no-op on an already-configured
        marketplace and does not refresh it, so without an explicit upgrade a
        re-run keeps serving a stale snapshot -- observed serving
        pre-monorepo content."""
        for path in (SH, PS1):
            with self.subTest(script=path.name):
                self.assertIn("marketplace upgrade", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
