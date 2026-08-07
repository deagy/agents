#!/usr/bin/env python3
"""Structural checks on what the packaged plugins actually declare.

Two classes of bug this catches, both of which had already shipped:

1. **Unparseable skill frontmatter.** Four hand-authored forge skills had a
   `description` containing `": "`, which ends a plain YAML scalar. The file
   looked completely normal, `claude plugin validate` reported "at runtime
   this skill loads with empty metadata (all frontmatter fields silently
   dropped)", and nothing else noticed -- a skill with no name or description
   is effectively undiscoverable.

2. **A dependency declared in the wrong shape.** `dependencies` is an array;
   the object form `{"cadre": ">=x"}` is rejected outright by Claude Code
   ("expected array, received object"), so a plugin declaring it that way
   installs with no dependency enforcement at all.

    python3 -m unittest discover -s plugin/tools -p "test_*.py"
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "plugin"

LIFECYCLE_PLUGINS = ("lifecycle", "lifecycle-github", "lifecycle-gitlab")
MANIFEST_KINDS = (".claude-plugin", ".codex-plugin")


def _manifest(directory: Path, kind: str) -> dict:
    return json.loads((directory / kind / "plugin.json").read_text(encoding="utf-8"))


class TestSkillFrontmatterParses(unittest.TestCase):
    def test_every_packaged_skill_has_parseable_frontmatter(self) -> None:
        broken: list[str] = []
        for path in sorted(PACKAGE_ROOT.rglob("SKILL.md")):
            if "node_modules" in path.parts:
                continue
            match = re.match(r"\A---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
            if match is None:
                broken.append(f"{path.relative_to(REPO_ROOT)}: no frontmatter block")
                continue
            try:
                parsed = yaml.safe_load(match.group(1))
            except yaml.YAMLError as error:
                broken.append(f"{path.relative_to(REPO_ROOT)}: {str(error).splitlines()[0]}")
                continue
            for field in ("name", "description"):
                if not (isinstance(parsed, dict) and str(parsed.get(field, "")).strip()):
                    broken.append(f"{path.relative_to(REPO_ROOT)}: empty {field}")

        self.assertEqual(
            broken,
            [],
            "Skill frontmatter must parse as YAML and carry a name and description. A plain "
            'scalar containing ": " ends the value early -- use a folded block scalar (>-) '
            "for prose.\n" + "\n".join(broken),
        )


class TestLifecyclePluginsDeclareTheirDependency(unittest.TestCase):
    """Every lifecycle skill shells out to `bin/cadre sdlc`, which exists only
    in the `cadre` plugin. That requirement used to be stated in prose in a
    `description` field and enforced by nothing."""

    def test_dependency_on_cadre_is_declared_in_array_form(self) -> None:
        for name in LIFECYCLE_PLUGINS:
            for kind in MANIFEST_KINDS:
                with self.subTest(plugin=name, manifest=kind):
                    dependencies = _manifest(PACKAGE_ROOT / "plugins" / name, kind).get("dependencies")
                    self.assertIsInstance(
                        dependencies, list, "dependencies must be an array, not an object"
                    )
                    names = {d["name"] if isinstance(d, dict) else d for d in dependencies}
                    self.assertIn("cadre", names)

    def test_the_cadre_plugin_itself_declares_no_dependencies(self) -> None:
        """It must stay standalone-installable -- being reachable from any
        project without pulling in lifecycle governance is its whole pitch."""
        for kind in MANIFEST_KINDS:
            with self.subTest(manifest=kind):
                self.assertNotIn("dependencies", _manifest(PACKAGE_ROOT, kind))


class TestHooksAreNotDoubleDeclared(unittest.TestCase):
    """`hooks/hooks.json` at the standard path loads automatically.

    Naming it in the manifest as well is not redundant-but-harmless: Claude
    Code reports "Duplicate hooks file detected" and the hook does not load
    at all. The manifest field is for *additional* hook files only. This
    shipped once already -- a SessionStart hook that looked correct in every
    static check and silently never ran.
    """

    def test_no_manifest_declares_the_standard_hooks_path(self) -> None:
        offenders = []
        for manifest_path in sorted(PACKAGE_ROOT.glob("plugins/*/.*-plugin/plugin.json")) + \
                             sorted(PACKAGE_ROOT.glob(".*-plugin/plugin.json")):
            declared = json.loads(manifest_path.read_text(encoding="utf-8")).get("hooks")
            if declared in ("./hooks/hooks.json", "hooks/hooks.json"):
                offenders.append(str(manifest_path.relative_to(REPO_ROOT)))
        self.assertEqual(
            offenders,
            [],
            "Remove the `hooks` field: hooks/hooks.json is loaded automatically, and "
            "declaring it makes the load fail as a duplicate.\n" + "\n".join(offenders),
        )

    def test_lifecycle_plugins_still_ship_a_hooks_file(self) -> None:
        """The field is removed, the file must remain."""
        for name in LIFECYCLE_PLUGINS:
            with self.subTest(plugin=name):
                self.assertTrue((PACKAGE_ROOT / "plugins" / name / "hooks" / "hooks.json").is_file())


class TestUserConfig(unittest.TestCase):
    def test_lifecycle_plugins_declare_the_documented_option_fields(self) -> None:
        # type/title/description are all required by Claude Code; a missing
        # one fails `claude plugin validate`.
        for name in LIFECYCLE_PLUGINS:
            for kind in MANIFEST_KINDS:
                options = _manifest(PACKAGE_ROOT / "plugins" / name, kind).get("userConfig", {})
                with self.subTest(plugin=name, manifest=kind):
                    self.assertIn("kernelInstall", options)
                    self.assertIn("profile", options)
                    for key, option in options.items():
                        for field in ("type", "title", "description"):
                            self.assertIn(field, option, f"{key} is missing {field}")

    def test_kernel_install_defaults_to_auto(self) -> None:
        for name in LIFECYCLE_PLUGINS:
            option = _manifest(PACKAGE_ROOT / "plugins" / name, ".claude-plugin")["userConfig"]
            with self.subTest(plugin=name):
                self.assertEqual("auto", option["kernelInstall"].get("default"))


if __name__ == "__main__":
    unittest.main()
