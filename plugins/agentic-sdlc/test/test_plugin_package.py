"""Repository-level packaging checks for the portable Codex plugin."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]
MARKETPLACE = REPOSITORY_ROOT / ".agents" / "plugins" / "marketplace.json"
EXPECTED_SKILLS = {
    "initialize-agentic-sdlc",
    "orchestrate-agentic-sdlc",
    "validate-agentic-sdlc",
    "review-lifecycle-gate",
    "invalidate-lifecycle-gates",
    "runtime-assurance-status",
}


class PluginPackageTests(unittest.TestCase):
    def test_manifest_and_marketplace_are_consistent(self) -> None:
        manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual("agentic-sdlc", manifest["name"])
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertNotIn("TODO", manifest_path.read_text(encoding="utf-8"))
        entry = next(item for item in marketplace["plugins"] if item["name"] == manifest["name"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_INSTALL", entry["policy"]["authentication"])
        source = entry["source"]["path"].removeprefix("./")
        self.assertEqual(PLUGIN_ROOT.resolve(), (REPOSITORY_ROOT / source).resolve())

    def test_all_skills_have_valid_minimal_metadata(self) -> None:
        skill_root = PLUGIN_ROOT / "skills"
        self.assertEqual(EXPECTED_SKILLS, {path.name for path in skill_root.iterdir() if path.is_dir()})
        for skill_name in EXPECTED_SKILLS:
            with self.subTest(skill=skill_name):
                skill_file = skill_root / skill_name / "SKILL.md"
                content = skill_file.read_text(encoding="utf-8")
                frontmatter = content.split("---", 2)[1]
                keys = {
                    line.split(":", 1)[0].strip()
                    for line in frontmatter.splitlines()
                    if re.match(r"^[a-z_]+:", line)
                }
                self.assertEqual({"name", "description"}, keys)
                self.assertIn(f"name: {skill_name}", frontmatter)
                self.assertTrue((skill_root / skill_name / "agents" / "openai.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
