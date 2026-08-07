"""Force the optional `mcp` package to be unimportable for a block of code.

`dispatch_server.py` and `gitlab_server.py` both fail closed with an
install pointer when `mcp` isn't installed, and that path has tests. Those
tests used to assert the *host's* state -- "the real 'mcp' package is not
installed in this environment" -- and `self.fail()` if any `mcp` module was
already loaded. That makes them pass or fail on a property of whoever's
machine is running them: green on a CI runner that never installs `mcp`,
red on any developer machine that has it, which increasingly means anyone
actually running the MCP servers this repository ships.

`mcp_unimportable()` simulates the absence instead, so the fail-closed path
is exercised identically either way. It installs a `sys.meta_path` finder
that raises `ImportError` for `mcp` and any `mcp.*` submodule, and hides
any already-imported `mcp*` modules for the duration, restoring both on
exit (including on exception).

Deliberately not named `test_*.py`, so `unittest discover -p "test_*.py"`
treats it as a helper rather than collecting it as a test module.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator, Sequence


class _BlockMcpFinder:
    """A `sys.meta_path` finder that refuses to import `mcp`.

    Placed at the front of `sys.meta_path`, so it is consulted before the
    normal path finders and wins even when the real package is installed.
    """

    def __init__(self, blocked_roots: Sequence[str]) -> None:
        self._blocked_roots = tuple(blocked_roots)

    def _is_blocked(self, fullname: str) -> bool:
        return any(
            fullname == root or fullname.startswith(f"{root}.") for root in self._blocked_roots
        )

    def find_module(self, fullname, path=None):  # noqa: D102 - legacy finder API, kept for safety
        return None

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102
        if self._is_blocked(fullname):
            raise ImportError(
                f"simulated absence of {fullname!r} (roster/orchestration/test/mcp_absence.py)",
                name=fullname,
            )
        return None


@contextlib.contextmanager
def mcp_unimportable(*, roots: Sequence[str] = ("mcp",)) -> Iterator[None]:
    """Make `import mcp` (and `mcp.*`) raise ImportError inside the block.

    Any `mcp*` entries already in `sys.modules` are removed for the
    duration and restored afterwards, so an installed-and-imported `mcp`
    can't satisfy the import from cache and later tests in the same process
    still see the real package.
    """
    finder = _BlockMcpFinder(roots)
    hidden = {
        name: module
        for name, module in sys.modules.items()
        if any(name == root or name.startswith(f"{root}.") for root in roots)
    }
    for name in hidden:
        del sys.modules[name]
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.meta_path.remove(finder)
        # Drop anything the block imported under a blocked root before
        # restoring, so a partially-initialized module can't leak out.
        for name in [
            name
            for name in sys.modules
            if any(name == root or name.startswith(f"{root}.") for root in roots)
        ]:
            del sys.modules[name]
        sys.modules.update(hidden)
