"""Dependency-free-at-import secure-cloud-agents MCP dispatch package.

`dispatch_core.py` is pure Python (stdlib only) and safe to import from
anywhere in this suite. `dispatch_server.py` is the thin `mcp` SDK adapter on
top of it and only requires the optional `mcp` dependency when actually run
(see `requirements-mcp.txt`).
"""
