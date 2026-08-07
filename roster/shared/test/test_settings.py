"""Unit coverage for roster/shared/src/settings.py -- the unified operator
settings resolver (env var > project-local file > user-global file >
static default > computed default > interactive prompt > fail-closed)."""

from __future__ import annotations

import builtins
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

import settings  # noqa: E402
from settings_test_helpers import isolate_settings  # noqa: E402  (same directory)


def _make_project(root: Path) -> Path:
    (root / ".git").mkdir()
    (root / ".agents").mkdir()
    return root


def _write_project_config(root: Path, text: str, *, filename: str = "cadre.yaml") -> Path:
    path = root / ".agents" / filename
    path.write_text(text, encoding="utf-8")
    return path


class SettingsTestCase(unittest.TestCase):
    """Common isolation: never read a real developer machine's
    ~/.config/cadre/config.yaml, and always reset settings.py's per-process
    file cache between tests."""

    def setUp(self) -> None:
        self.xdg_config_home = isolate_settings(self)
        self.project_dir = Path(tempfile.mkdtemp(prefix="cadre-settings-project-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.project_dir, ignore_errors=True))
        _make_project(self.project_dir)


class PrecedenceMatrixTests(SettingsTestCase):
    def test_env_wins_over_everything(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "from-project"\n')
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'gitlab:\n  project_id: "from-global"\n', encoding="utf-8"
        )
        settings.reset_cache()
        value = settings.resolve_setting(
            "gitlab.project_id", start=self.project_dir, env={"GITLAB_DOCS_PROJECT_ID": "from-env"}
        )
        self.assertEqual(value, "from-env")

    def test_project_file_wins_over_global_file(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "from-project"\n')
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'gitlab:\n  project_id: "from-global"\n', encoding="utf-8"
        )
        settings.reset_cache()
        value = settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        self.assertEqual(value, "from-project")

    def test_global_file_wins_over_default(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'runners:\n  claude_bin: "/opt/bin/claude"\n', encoding="utf-8"
        )
        settings.reset_cache()
        value = settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertEqual(value, "/opt/bin/claude")

    def test_static_default_used_when_nothing_else_resolves(self) -> None:
        value = settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertEqual(value, "claude")

    def test_computed_default_used_when_nothing_else_resolves(self) -> None:
        with mock.patch.object(settings.shutil, "which", return_value="/usr/local/bin/agentic-sdlc"):
            value = settings.resolve_setting("agentic_sdlc.bin_path", start=self.project_dir, env={})
        self.assertEqual(value, "/usr/local/bin/agentic-sdlc")

    def test_prompt_used_when_nothing_else_resolves(self) -> None:
        inputs = iter(["https://prompted.example.com", "skip"])
        with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(
            sys.stdout, "isatty", return_value=True
        ):
            value = settings.resolve_setting(
                "gitlab.base_url",
                start=self.project_dir,
                env={"CADRE_INTERACTIVE": "1"},
                input_func=lambda _prompt: next(inputs),
                output_func=lambda _text: None,
            )
        self.assertEqual(value, "https://prompted.example.com")

    def test_required_field_fails_closed_when_totally_unresolved(self) -> None:
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.base_url", start=self.project_dir, env={})
        message = str(ctx.exception)
        self.assertIn("gitlab.base_url", message)
        self.assertIn("GITLAB_BASE_URL", message)
        self.assertIn("checked:", message)

    def test_optional_field_returns_none_instead_of_raising(self) -> None:
        value = settings.resolve_optional("knowledge_store.home", start=self.project_dir, env={})
        self.assertIsNone(value)

    def test_optional_field_still_raises_on_a_global_only_scope_violation(self) -> None:
        # resolve_optional() swallows "simply unconfigured" (above), but a
        # project-local file setting a global_only field is a security
        # event, not an ordinary absence -- it must surface even through
        # the "optional" resolver, never silently degrade to None.
        _write_project_config(
            self.project_dir, 'agentic_sdlc:\n  bin_path: "/tmp/should-not-be-honored"\n'
        )
        with self.assertRaises(settings.SettingsScopeError) as ctx:
            settings.resolve_optional("agentic_sdlc.bin_path", start=self.project_dir, env={})
        self.assertIn("agentic_sdlc.bin_path", str(ctx.exception))


class EmptyEnvVarTests(SettingsTestCase):
    def test_empty_env_var_errors_rather_than_falling_back(self) -> None:
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting(
                "runners.claude_bin", start=self.project_dir, env={"SECURE_CLOUD_AGENTS_CLAUDE_BIN": ""}
            )
        self.assertIn("SECURE_CLOUD_AGENTS_CLAUDE_BIN", str(ctx.exception))

    def test_whitespace_only_env_var_errors(self) -> None:
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting(
                "runners.claude_bin", start=self.project_dir, env={"SECURE_CLOUD_AGENTS_CLAUDE_BIN": "   "}
            )


class GlobalOnlyScopeTests(SettingsTestCase):
    def test_project_local_file_setting_a_global_only_field_is_rejected(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  base_url: "https://evil.example.com"\n')
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.base_url", start=self.project_dir, env={})
        message = str(ctx.exception)
        self.assertIn("gitlab.base_url", message)
        self.assertIn("project-local", message)

    def test_project_local_file_setting_a_project_or_global_field_is_honored(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "42"\n')
        value = settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        self.assertEqual(value, "42")

    def test_global_file_may_set_a_global_only_field(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'gitlab:\n  base_url: "https://ok.example.com"\n', encoding="utf-8"
        )
        settings.reset_cache()
        value = settings.resolve_setting("gitlab.base_url", start=self.project_dir, env={})
        self.assertEqual(value, "https://ok.example.com")


class SecretShapedKeyTests(SettingsTestCase):
    def test_secret_shaped_key_in_project_file_is_rejected_without_echoing_value(self) -> None:
        _write_project_config(
            self.project_dir, 'gitlab:\n  svc_token: "glpat-super-secret-value"\n  project_id: "1"\n'
        )
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        message = str(ctx.exception)
        self.assertIn("svc_token", message)
        self.assertNotIn("glpat-super-secret-value", message)

    def test_secret_shaped_key_in_global_file_is_rejected(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'embedding:\n  api_key: "sk-super-secret"\n', encoding="utf-8"
        )
        settings.reset_cache()
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertNotIn("sk-super-secret", str(ctx.exception))

    def test_various_secret_shaped_leaf_names_are_all_rejected(self) -> None:
        for leaf in ("token", "api_key", "password", "secret", "svc_token", "custom_token"):
            with self.subTest(leaf=leaf):
                project = Path(tempfile.mkdtemp(prefix="cadre-settings-secret-"))
                self.addCleanup(lambda p=project: __import__("shutil").rmtree(p, ignore_errors=True))
                _make_project(project)
                _write_project_config(project, f'gitlab:\n  {leaf}: "x"\n  project_id: "1"\n')
                settings.reset_cache()
                with self.assertRaises(settings.SettingsError):
                    settings.resolve_setting("gitlab.project_id", start=project, env={})


class TristateHierarchyFlagTests(SettingsTestCase):
    def _resolve(self, raw_yaml_value: str) -> object:
        _write_project_config(
            self.project_dir, f"gitlab:\n  supports_work_item_hierarchy: {raw_yaml_value}\n"
        )
        settings.reset_cache()
        return settings.resolve_setting(
            "gitlab.supports_work_item_hierarchy", start=self.project_dir, env={}
        )

    def test_absent_resolves_to_none(self) -> None:
        value = settings.resolve_setting(
            "gitlab.supports_work_item_hierarchy", start=self.project_dir, env={}
        )
        self.assertIsNone(value)

    def test_native_true(self) -> None:
        self.assertIs(self._resolve("true"), True)

    def test_native_false(self) -> None:
        self.assertIs(self._resolve("false"), False)

    def test_string_true_quoted(self) -> None:
        self.assertIs(self._resolve('"true"'), True)

    def test_string_true_case_insensitive(self) -> None:
        self.assertIs(self._resolve('"TRUE"'), True)

    def test_explicit_null_falls_through_to_default_none(self) -> None:
        self.assertIsNone(self._resolve("~"))

    def test_invalid_string_rejected(self) -> None:
        with self.assertRaises(settings.SettingsError):
            self._resolve('"maybe"')

    def test_env_var_string_true_false_and_invalid(self) -> None:
        self.assertIs(
            settings.resolve_setting(
                "gitlab.supports_work_item_hierarchy",
                start=self.project_dir,
                env={"GITLAB_SUPPORTS_WORK_ITEM_HIERARCHY": "true"},
            ),
            True,
        )
        self.assertIs(
            settings.resolve_setting(
                "gitlab.supports_work_item_hierarchy",
                start=self.project_dir,
                env={"GITLAB_SUPPORTS_WORK_ITEM_HIERARCHY": "FALSE"},
            ),
            False,
        )
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting(
                "gitlab.supports_work_item_hierarchy",
                start=self.project_dir,
                env={"GITLAB_SUPPORTS_WORK_ITEM_HIERARCHY": "maybe"},
            )


class YamlScalarHazardTests(SettingsTestCase):
    def test_unquoted_numeric_project_id_is_rejected(self) -> None:
        _write_project_config(self.project_dir, "gitlab:\n  project_id: 007\n")
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        self.assertIn("project_id", str(ctx.exception))

    def test_tilde_project_id_is_treated_as_unset_at_this_tier(self) -> None:
        _write_project_config(self.project_dir, "gitlab:\n  project_id: ~\n")
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        # required field, unset everywhere -> fail-closed, not a validation
        # error about the null itself.
        self.assertIn("is not configured", str(ctx.exception))

    def test_yes_no_bool_coercion_rejected_for_string_fields(self) -> None:
        _write_project_config(self.project_dir, "gitlab:\n  project_id: yes\n")
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})

    def test_yes_no_bool_coercion_rejected_for_executable_fields(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            "runners:\n  claude_bin: no\n", encoding="utf-8"
        )
        settings.reset_cache()
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})

    def test_relative_executable_path_with_separator_is_rejected(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'runners:\n  claude_bin: "./claude"\n', encoding="utf-8"
        )
        settings.reset_cache()
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})

    def test_bare_executable_name_without_separator_is_accepted(self) -> None:
        (self.xdg_config_home / "cadre").mkdir(parents=True)
        (self.xdg_config_home / "cadre" / "config.yaml").write_text(
            'runners:\n  claude_bin: "my-claude"\n', encoding="utf-8"
        )
        settings.reset_cache()
        value = settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertEqual(value, "my-claude")


class MissingPyYamlAndDualFileTests(SettingsTestCase):
    def test_missing_pyyaml_raises_clear_error_naming_the_file(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "1"\n')
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("simulated: PyYAML not installed")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertRaises(settings.SettingsError) as ctx:
                settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        message = str(ctx.exception)
        self.assertIn("cadre.yaml", message)

    def test_both_yaml_and_json_present_at_project_tier_is_an_error(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "1"\n')
        (self.project_dir / ".agents" / "cadre.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        self.assertIn("cadre.yaml", str(ctx.exception))
        self.assertIn("cadre.json", str(ctx.exception))

    def test_both_yaml_and_json_present_at_global_tier_is_an_error(self) -> None:
        directory = self.xdg_config_home / "cadre"
        directory.mkdir(parents=True)
        (directory / "config.yaml").write_text("{}", encoding="utf-8")
        (directory / "config.json").write_text("{}", encoding="utf-8")
        settings.reset_cache()
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertIn("config.yaml", str(ctx.exception))
        self.assertIn("config.json", str(ctx.exception))


class AtomicWriteTests(SettingsTestCase):
    def test_round_trip_preserves_unknown_keys_uses_replace_and_correct_mode(self) -> None:
        directory = self.xdg_config_home / "cadre"
        directory.mkdir(parents=True)
        (directory / "config.yaml").write_text(
            "unrelated_top_level: keep-me\nrunners:\n  codex_bin: \"codex-keep\"\n", encoding="utf-8"
        )
        settings.reset_cache()

        with mock.patch.object(settings.os, "replace", wraps=settings.os.replace) as replace_spy:
            written_path = settings.write_setting("runners.claude_bin", "my-claude", tier="global")
            self.assertTrue(replace_spy.called)

        text = written_path.read_text(encoding="utf-8")
        self.assertIn("unrelated_top_level", text)
        self.assertIn("codex-keep", text)
        self.assertIn("my-claude", text)
        self.assertIn("schema_version", text)
        # header regenerated
        self.assertIn("Generated by cadre's settings resolver", text)

        mode = os.stat(written_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

        settings.reset_cache()
        value = settings.resolve_setting("runners.claude_bin", start=self.project_dir, env={})
        self.assertEqual(value, "my-claude")

    def test_project_tier_write_creates_file_and_is_readable(self) -> None:
        path = settings.write_setting("gitlab.project_id", "99", tier="project", start=self.project_dir)
        self.assertTrue(path.is_file())
        settings.reset_cache()
        value = settings.resolve_setting("gitlab.project_id", start=self.project_dir, env={})
        self.assertEqual(value, "99")

    def test_global_only_field_cannot_be_written_to_project_tier(self) -> None:
        with self.assertRaises(settings.SettingsError):
            settings.write_setting("gitlab.base_url", "https://x.example.com", tier="project", start=self.project_dir)


class SymlinkEscapeTests(SettingsTestCase):
    def test_symlinked_agents_directory_write_is_rejected(self) -> None:
        outside = Path(tempfile.mkdtemp(prefix="cadre-settings-outside-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (self.project_dir / ".agents").rmdir()
        (self.project_dir / ".agents").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(settings.SettingsError) as ctx:
            settings.write_setting("gitlab.project_id", "1", tier="project", start=self.project_dir)
        self.assertIn("symlink", str(ctx.exception).lower())
        self.assertFalse((outside / "cadre.yaml").exists())


class NonInteractivePathNeverPromptsTests(SettingsTestCase):
    def _boom(self, _prompt: str) -> str:
        raise AssertionError("input_func should never be called on a non-interactive path")

    def test_no_cadre_interactive_env_var_never_prompts(self) -> None:
        with self.assertRaises(settings.SettingsError):
            settings.resolve_setting(
                "gitlab.base_url", start=self.project_dir, env={}, input_func=self._boom
            )

    def test_cadre_interactive_set_but_no_tty_never_prompts(self) -> None:
        with mock.patch.object(sys.stdin, "isatty", return_value=False), mock.patch.object(
            sys.stdout, "isatty", return_value=True
        ):
            with self.assertRaises(settings.SettingsError):
                settings.resolve_setting(
                    "gitlab.base_url",
                    start=self.project_dir,
                    env={"CADRE_INTERACTIVE": "1"},
                    input_func=self._boom,
                )

    def test_disable_interactive_overrides_a_real_tty_and_the_env_var(self) -> None:
        settings.disable_interactive()
        self.addCleanup(lambda: setattr(settings, "_INTERACTIVE_DISABLED", False))
        with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(
            sys.stdout, "isatty", return_value=True
        ):
            with self.assertRaises(settings.SettingsError):
                settings.resolve_setting(
                    "gitlab.base_url",
                    start=self.project_dir,
                    env={"CADRE_INTERACTIVE": "1"},
                    input_func=self._boom,
                )


class EnvAllowlistTests(unittest.TestCase):
    def test_cadre_interactive_is_absent_from_dispatch_core_env_allowlist(self) -> None:
        mcp_dir = Path(__file__).resolve().parents[2] / "orchestration" / "mcp"
        if str(mcp_dir) not in sys.path:
            sys.path.append(str(mcp_dir))
        import dispatch_core  # noqa: E402  (sys.path set above)

        self.assertNotIn(settings.INTERACTIVE_ENV_VAR, dispatch_core.ENV_ALLOWLIST)


class EffectiveSettingsAndCliTests(SettingsTestCase):
    def test_effective_settings_never_raises_and_covers_every_known_key(self) -> None:
        results = settings.effective_settings(start=self.project_dir, env={})
        keys = {resolved.key for resolved in results}
        self.assertEqual(keys, set(settings.known_keys()))

    def test_effective_settings_never_prompts(self) -> None:
        with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(
            sys.stdout, "isatty", return_value=True
        ):
            # Even with CADRE_INTERACTIVE=1 and a "tty", effective_settings()
            # must never block on input() -- it backs a non-interactive
            # `cadre config show`.
            results = settings.effective_settings(
                start=self.project_dir, env={"CADRE_INTERACTIVE": "1"}
            )
        self.assertTrue(results)

    def test_config_path_cli_reports_project_and_global_paths(self) -> None:
        _write_project_config(self.project_dir, 'gitlab:\n  project_id: "1"\n')
        with mock.patch.object(settings.Path, "cwd", return_value=self.project_dir):
            exit_code = settings.main(["path"])
        self.assertEqual(exit_code, 0)


class ResolveManyTests(SettingsTestCase):
    def test_resolve_many_returns_a_dict_for_every_key(self) -> None:
        values = settings.resolve_many(
            ["runners.claude_bin", "runners.codex_bin"], start=self.project_dir, env={}
        )
        self.assertEqual(values, {"runners.claude_bin": "claude", "runners.codex_bin": "codex"})


if __name__ == "__main__":
    unittest.main()
