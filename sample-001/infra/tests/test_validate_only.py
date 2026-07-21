from __future__ import annotations

import pathlib
import json
import re
import unittest


TERRAFORM = pathlib.Path(__file__).resolve().parents[1] / "terraform"


def source_without_comments(path: pathlib.Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line.split("#", 1)[0] for line in lines)


def json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(json_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(json_keys(item) for item in value))
    return set()


class ValidateOnlyTerraformTests(unittest.TestCase):
    def test_contract_contains_no_infrastructure_or_state_blocks(self) -> None:
        text = "\n".join(source_without_comments(path) for path in TERRAFORM.rglob("*.tf"))
        forbidden_blocks = (
            "provider", "backend", "resource", "data", "provisioner",
            "terraform_remote_state", "import", "moved", "removed", "module",
        )
        for keyword in forbidden_blocks:
            with self.subTest(keyword=keyword):
                self.assertIsNone(re.search(rf"(?m)^\s*{keyword}\s*(?:\"|{{)", text))
        for path in TERRAFORM.rglob("*.tf.json"):
            keys = json_keys(json.loads(path.read_text(encoding="utf-8")))
            self.assertTrue(keys.isdisjoint(forbidden_blocks), f"forbidden Terraform JSON key in {path}: {keys & set(forbidden_blocks)}")

    def test_contract_pins_terraform_and_outputs_are_not_sensitive(self) -> None:
        text = "\n".join(source_without_comments(path) for path in TERRAFORM.rglob("*.tf"))
        self.assertIn('required_version = "= 1.14.5"', text)
        self.assertNotIn("sensitive = true", text)

    def test_json_key_walk_detects_nested_forbidden_blocks(self) -> None:
        self.assertIn("resource", json_keys({"terraform": {"nested": [{"resource": {}}]}}))

    def test_example_is_non_secret_and_local(self) -> None:
        example = (TERRAFORM / "examples/local.tfvars.example").read_text(encoding="utf-8").lower()
        self.assertIn('environment    = "local"', example)
        for token in ("password", "secret", "token", "private_key"):
            self.assertNotIn(token, example)


if __name__ == "__main__":
    unittest.main()
