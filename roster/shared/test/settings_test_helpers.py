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
