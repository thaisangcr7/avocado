"""The MCP servers an operator has connected, and the client for each.

One place owns two things that must not be spread around: which servers exist,
and how a credential is found. Everything else asks this for a transport by
slug and never learns where the token came from.

Clients are cached per slug because each holds a negotiated session, and
re-handshaking on every turn would spend a round trip to learn what we already
knew.
"""

from __future__ import annotations

import os

from app.clients.tools.base import ToolTransport
from app.clients.tools.mcp_client import McpClient
from app.core.config import McpServerConfig
from app.core.logging import get_logger

log = get_logger(__name__)


class McpServers:
    """Every configured server, keyed by slug."""

    def __init__(self, servers: list[McpServerConfig], *, timeout: float = 30.0) -> None:
        self._configs = {server.slug: server for server in servers}
        self._timeout = timeout
        self._clients: dict[str, ToolTransport] = {}

    @property
    def configs(self) -> list[McpServerConfig]:
        return list(self._configs.values())

    def get(self, slug: str) -> McpServerConfig | None:
        return self._configs.get(slug)

    def transport(self, slug: str) -> ToolTransport | None:
        """The client for one server, built once and kept.

        The credential is read from the environment here, at the last possible
        moment, and handed straight to the transport. It is never stored in the
        configuration object, which is logged on boot and copied into every
        worker.
        """
        if slug in self._clients:
            return self._clients[slug]

        config = self._configs.get(slug)
        if config is None:
            return None

        token = os.environ.get(config.auth_ref) if config.auth_ref else None
        if config.auth_ref and not token:
            # Boot-time validation catches this, so reaching it means the
            # environment changed underneath a running process. Calling
            # unauthenticated would be worse than not calling.
            log.warning("mcp_credential_missing", server=config.slug, variable=config.auth_ref)
            return None

        client = McpClient(
            url=config.url,
            token=token,
            timeout=self._timeout,
            # The slug, never the URL: a hosted server's URL can itself carry a
            # credential in a query string.
            label=config.slug,
        )
        self._clients[slug] = client
        return client
