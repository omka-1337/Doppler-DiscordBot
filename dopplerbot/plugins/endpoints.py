"""HTTP endpoints declared by plugins.

Some settings pages cannot be a generated form -- the embed builder is the
example -- and those need somewhere for their own requests to go. A plugin
registers a handler here and it becomes reachable at
``/api/plugin/<plugin_id>/<path>`` on the dashboard, behind the same login as
everything else.

Routes are kept in this registry rather than added to the bot's router: aiohttp
freezes its router once the app starts, and plugins load and unload long after
that. One catch-all route in the bot dispatches through here instead, which
also makes unregistering a plugin's endpoints trivial.
"""

import logging
import re
from typing import Awaitable, Callable

log = logging.getLogger("plugins.endpoints")

Handler = Callable[..., Awaitable]

# (plugin_id, METHOD, /path) -> handler
_REGISTRY: dict[tuple[str, str, str], Handler] = {}

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._~\-/]*$")


class EndpointError(Exception):
    """Raised for an invalid or conflicting endpoint declaration."""


def normalise(method: str, path: str) -> tuple[str, str]:
    method = method.upper()
    if method not in ALLOWED_METHODS:
        raise EndpointError(f"Unsupported method {method!r}.")

    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/") or "/"

    if not _PATH_PATTERN.match(path) or ".." in path:
        raise EndpointError(f"Invalid endpoint path {path!r}.")

    return method, path


def register(plugin_id: str, method: str, path: str, handler: Handler) -> str:
    method, path = normalise(method, path)
    key = (plugin_id, method, path)

    if key in _REGISTRY:
        raise EndpointError(f"{plugin_id!r} already declares {method} {path}.")

    _REGISTRY[key] = handler
    log.info("Plugin %r registered %s %s", plugin_id, method, path)
    return f"/api/plugin/{plugin_id}{path}"


def unregister_plugin(plugin_id: str) -> int:
    doomed = [k for k in _REGISTRY if k[0] == plugin_id]
    for key in doomed:
        del _REGISTRY[key]
    return len(doomed)


def lookup(plugin_id: str, method: str, path: str) -> Handler | None:
    try:
        method, path = normalise(method, path)
    except EndpointError:
        return None
    return _REGISTRY.get((plugin_id, method, path))


def declared() -> list[dict]:
    """For the dashboard, so a plugin's own page knows what it may call."""
    return [
        {"plugin": pid, "method": m, "path": p, "url": f"/api/plugin/{pid}{p}"}
        for (pid, m, p) in sorted(_REGISTRY)
    ]
