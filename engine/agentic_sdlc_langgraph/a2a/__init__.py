"""A2A (Agent2Agent) protocol support: a server surface (`server.py`,
mounted into `service.py`'s FastAPI app) exposing this engine's SDLC task
lifecycle to external A2A callers, and a client surface (`client.py`,
used by `agents.A2AModelClient`) for dispatching an author/reviewer node
to an external A2A-reachable agent. `types.py` holds the shared,
hand-written pydantic models mirroring the public A2A wire format.
"""

from __future__ import annotations
