"""The MCP servers an operator has connected, and the client for each.

One place owns two things that must not be spread around: which servers exist,
and how a credential is found. Everything else asks this for a transport by
slug and never learns where the token came from.

Clients are cached per slug because each holds a negotiated session, and
re-handshaking on every turn would spend a round trip to learn what we already
knew.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from app.clients.tools.base import RemoteTool, ToolTransport, ToolTransportError
from app.clients.tools.mcp_client import McpClient
from app.core.config import McpServerConfig
from app.core.logging import get_logger

log = get_logger(__name__)

# How long a listing stands before it is fetched again. Long enough that
# opening the tool picker twice does not cost two round trips per server, short
# enough that a server coming back is noticed without a restart.
LISTING_TTL_SECONDS = 60.0

# A failed probe is remembered too, for less time. Without this, one unreachable
# server costs the probe timeout on every picker open.
FAILURE_TTL_SECONDS = 20.0

# The picker waits on this, so it cannot be the ordinary call timeout. A server
# that is merely slow is reported as unreachable rather than holding the UI.
PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class ServerListing:
    """What a server last said it offers, and whether it answered at all."""

    reachable: bool
    tools: list[RemoteTool] = field(default_factory=list)
    fetched_at: float = 0.0

    @property
    def ttl(self) -> float:
        return LISTING_TTL_SECONDS if self.reachable else FAILURE_TTL_SECONDS

    def fresh(self, now: float) -> bool:
        return now - self.fetched_at < self.ttl


class McpServers:
    """Every configured server, keyed by slug."""

    def __init__(self, servers: list[McpServerConfig], *, timeout: float = 30.0) -> None:
        self._configs = {server.slug: server for server in servers}
        self._timeout = timeout
        self._clients: dict[str, ToolTransport] = {}
        self._listings: dict[str, ServerListing] = {}

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

    async def listing(self, slug: str, *, refresh: bool = False) -> ServerListing:
        """What one server offers, cached, and whether it answered.

        Both callers need this and neither should pay for the other: the picker
        asks so it can show a server's health and what its schemas cost, and a
        turn asks so it can offer the tools. Listing once and sharing it is why
        opening the picker does not make the next question slower.
        """
        now = time.monotonic()
        cached = self._listings.get(slug)
        if cached is not None and not refresh and cached.fresh(now):
            return cached

        transport = self.transport(slug)
        if transport is None:
            listing = ServerListing(reachable=False, fetched_at=now)
            self._listings[slug] = listing
            return listing

        try:
            tools = await asyncio.wait_for(transport.list_tools(), timeout=PROBE_TIMEOUT_SECONDS)
        except (ToolTransportError, TimeoutError):
            # Slow is reported the same as down. A user waiting on the picker
            # cannot tell the difference, and neither can a turn.
            log.info("mcp_listing_failed", server=slug)
            listing = ServerListing(reachable=False, fetched_at=now)
        else:
            listing = ServerListing(reachable=True, tools=list(tools), fetched_at=now)

        self._listings[slug] = listing
        return listing

    async def listings(self, slugs: list[str]) -> dict[str, ServerListing]:
        """Several at once. One slow server should not serialise behind another."""
        if not slugs:
            return {}
        results = await asyncio.gather(*(self.listing(slug) for slug in slugs))
        return dict(zip(slugs, results, strict=True))
