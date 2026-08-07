"""Shared test-isolation helper for `roster/shared/src/settings.py`.

Any test that resolves a setting risks reading the real developer machine's
`${XDG_CONFIG_HOME:-~/.config}/cadre/config.yaml` and becoming
machine-dependent unless it redirects `XDG_CONFIG_HOME` to a disposable temp
directory and clears `settings.py`'s per-process file cache both before and
after. Reused across `roster/shared/test/` and `roster/knowledge-store/test/`
rather than duplicated per test module.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))

import settings  # noqa: E402  (sys.path set above)


def isolate_settings(testcase) -> Path:
    """Redirect the user-global settings tier to a fresh, empty temp
    directory for the duration of `testcase`, and reset `settings.py`'s
    per-process file cache before and after. Registers cleanup via
    `testcase.addCleanup` so ordinary `setUp()` usage is enough. Returns the
    temp directory Path (the new `XDG_CONFIG_HOME`)."""
    tmp = tempfile.TemporaryDirectory(prefix="cadre-settings-test-")
    testcase.addCleanup(tmp.cleanup)
    patcher = mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp.name})
    patcher.start()
    testcase.addCleanup(patcher.stop)
    settings.reset_cache()
    testcase.addCleanup(settings.reset_cache)
    return Path(tmp.name)


class _ModuleIsolation:
    """start()/stop() counterpart to `isolate_settings`, for test modules
    that isolate once in `setUpModule`/`tearDownModule` rather than per
    `TestCase` (e.g. because most tests in the module already supply every
    setting via an explicit env dict, and only a handful that pop an env
    var actually risk falling through to the real global config file --
    module-wide isolation covers those without adding per-class setUp
    boilerplate)."""

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._patcher: mock._patch[dict] | None = None

    def start(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory(prefix="cadre-settings-test-")
        self._patcher = mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": self._tmp.name})
        self._patcher.start()
        settings.reset_cache()
        return Path(self._tmp.name)

    def stop(self) -> None:
        settings.reset_cache()
        if self._patcher is not None:
            self._patcher.stop()
        if self._tmp is not None:
            self._tmp.cleanup()


def isolate_settings_module() -> _ModuleIsolation:
    """Module-level counterpart to `isolate_settings` -- call `.start()`
    from `setUpModule` and `.stop()` from `tearDownModule`."""
    return _ModuleIsolation()
