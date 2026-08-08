#!/usr/bin/env python3
"""Guard the dependency closure Cline needs for a Git-source install.

Cline discovers the three TypeScript entrypoints from the repository root
when a user runs ``cline plugin install https://github.com/deagy/cadre``.
Unlike this repository's development workspace, that installation resolves
bare runtime imports from a root ``node_modules``.  Keep the manifest and
lockfile that create it small, explicit, and independent from the Claude
Code/Codex marketplace package under ``plugin/``.

The root closure and ``cline-plugins/`` declare the same runtime packages
twice, and Dependabot updates them on independent pull requests, so either
side can be bumped alone.  A divergence would be invisible: CI would keep
testing ``cline-plugins/``'s versions while a Git-source install shipped the
root's.  Nothing here is hardcoded for that reason -- the expected closure is
derived from the workspace manifests, so drift fails rather than passing
against a stale literal.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINTS = (
    "./cline-plugins/cline-agents/index.ts",
    "./cline-plugins/cline-lifecycle/index.ts",
    "./cline-plugins/cline/index.ts",
)
# Supplied by Cline's host sandbox at runtime, so deliberately absent from the
# root closure even though the workspace packages declare them.
HOST_SUPPLIED_SCOPE = "@cline/"


def _read_json(*parts: str) -> dict:
    return json.loads((REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


def _workspace_runtime_dependencies() -> dict[str, dict[str, str]]:
    """Map each plugin-owned runtime package to {workspace: declared version}.

    Returning every declaration, rather than a collapsed name->version dict,
    lets the tests below report *which* workspace disagrees when two of them
    pin the same package differently.
    """
    declarations: dict[str, dict[str, str]] = {}
    for entrypoint in ENTRYPOINTS:
        workspace = Path(entrypoint).parent.name
        manifest = _read_json("cline-plugins", workspace, "package.json")
        for name, version in manifest.get("dependencies", {}).items():
            if name.startswith(HOST_SUPPLIED_SCOPE):
                continue
            declarations.setdefault(name, {})[workspace] = version
    return declarations


class TestClineGitPluginPackaging(unittest.TestCase):
    def setUp(self) -> None:
        self.declarations = _workspace_runtime_dependencies()
        self.assertTrue(
            self.declarations,
            "no plugin-owned runtime dependencies found in cline-plugins/*/package.json;"
            " the derivation below would vacuously pass",
        )

    def test_workspaces_agree_on_every_shared_runtime_dependency(self) -> None:
        for name, by_workspace in self.declarations.items():
            with self.subTest(dependency=name):
                self.assertEqual(
                    len(set(by_workspace.values())),
                    1,
                    f"cline-plugins workspaces pin conflicting {name} versions:"
                    f" {by_workspace}. The root closure can only carry one, so a"
                    " Git-source install would ship the wrong version to at least"
                    " one entrypoint.",
                )

    def test_root_manifest_explicitly_declares_all_discovered_entrypoints(self) -> None:
        manifest = _read_json("package.json")
        self.assertTrue(manifest["private"])
        self.assertEqual(manifest["cline"]["plugins"], [{"paths": list(ENTRYPOINTS)}])
        self.assertNotIn("workspaces", manifest)
        self.assertNotIn("devDependencies", manifest)
        for entrypoint in ENTRYPOINTS:
            self.assertTrue((REPO_ROOT / entrypoint.removeprefix("./")).is_file())

    def test_root_manifest_matches_the_workspace_runtime_dependencies(self) -> None:
        expected = {
            name: sorted(by_workspace.values())[0]
            for name, by_workspace in self.declarations.items()
        }
        self.assertEqual(
            _read_json("package.json")["dependencies"],
            expected,
            "root package.json has drifted from cline-plugins/*/package.json."
            " Bump both sides together: the root closure is what a"
            " `cline plugin install <git-url>` actually resolves.",
        )

    def test_root_lockfile_pins_the_runtime_dependency_closure(self) -> None:
        manifest_dependencies = _read_json("package.json")["dependencies"]
        lockfile = _read_json("package-lock.json")
        self.assertEqual(lockfile["lockfileVersion"], 3)
        self.assertEqual(lockfile["packages"][""]["dependencies"], manifest_dependencies)
        for dependency, version in manifest_dependencies.items():
            with self.subTest(dependency=dependency):
                self.assertEqual(
                    lockfile["packages"][f"node_modules/{dependency}"]["version"], version
                )

    def test_both_lockfiles_resolve_the_same_runtime_versions(self) -> None:
        root = _read_json("package-lock.json")["packages"]
        workspace = _read_json("cline-plugins", "package-lock.json")["packages"]
        for dependency in _read_json("package.json")["dependencies"]:
            # Only the hoisted top-level entry is comparable; a nested
            # node_modules/<other>/node_modules/<dep> belongs to an unrelated
            # transitive dependant.
            key = f"node_modules/{dependency}"
            with self.subTest(dependency=dependency):
                self.assertIn(key, workspace)
                self.assertEqual(
                    root[key]["version"],
                    workspace[key]["version"],
                    f"{dependency} resolves to different versions in the root"
                    " lockfile and cline-plugins/package-lock.json. CI tests the"
                    " latter; a Git-source install ships the former.",
                )
                self.assertEqual(root[key]["integrity"], workspace[key]["integrity"])

    def test_claude_and_codex_marketplace_package_remains_npm_free(self) -> None:
        manifests = [
            path.relative_to(REPO_ROOT)
            for path in (REPO_ROOT / "plugin").rglob("package.json")
            if "node_modules" not in path.parts
        ]
        self.assertEqual(manifests, [])


if __name__ == "__main__":
    unittest.main()
