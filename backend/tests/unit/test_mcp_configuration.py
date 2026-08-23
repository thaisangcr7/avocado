"""Connecting a server is configuration, not code.

The claim `tool_catalogue` makes in its own docstring — that turning a
placeholder into a working integration is a config change — is either true or
it is a comment. These assert it, along with the boot-time refusals that stop a
misconfigured server from failing quietly at call time instead.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import McpServerConfig, Settings
from app.models.enums import ToolCategory, ToolKind
from app.services.tool_catalogue import BUILTIN_TOOLS, catalogue_for


def server(**overrides) -> McpServerConfig:
    return McpServerConfig(
        **{
            "slug": "wiki",
            "name": "Confluence",
            "url": "https://wiki.example.com/mcp",
            **overrides,
        }
    )


def settings_with(servers: list[dict], **overrides) -> Settings:
    parsed = [McpServerConfig(**s) for s in servers]
    return Settings(app_env="test", mcp_servers=parsed, **overrides)


# --- the catalogue --------------------------------------------------------


def test_a_configured_server_replaces_the_placeholder_of_the_same_name():
    catalogue = catalogue_for([server(description="Our knowledge base.")])

    wiki = next(t for t in catalogue if t.slug == "wiki")
    assert wiki.kind is ToolKind.MCP
    assert wiki.name == "Confluence"
    assert wiki.description == "Our knowledge base."
    # Replaced, not duplicated: the card the user already saw becomes live.
    assert sum(1 for t in catalogue if t.slug == "wiki") == 1


def test_a_placeholder_keeps_its_wording_when_the_config_does_not_override_it():
    catalogue = catalogue_for([server()])

    wiki = next(t for t in catalogue if t.slug == "wiki")
    assert wiki.description == "Read your team's knowledge base."


def test_a_server_the_catalogue_never_anticipated_is_simply_added():
    catalogue = catalogue_for([server(slug="crm", name="CRM", category="data")])

    crm = next(t for t in catalogue if t.slug == "crm")
    assert crm.kind is ToolKind.MCP
    assert crm.category is ToolCategory.DATA
    assert len(catalogue) == len(BUILTIN_TOOLS) + 1


def test_configuration_cannot_shadow_a_real_builtin():
    """Those are served in-process; a remote server taking the name would
    replace working code with whatever that server does."""
    catalogue = catalogue_for([server(slug="web-search", name="Not really web search")])

    web = next(t for t in catalogue if t.slug == "web-search")
    assert web.kind is ToolKind.BUILTIN
    assert web.name == "Web search"


def test_nothing_is_switched_on_just_by_being_connected():
    """Connecting a server must not start sending every conversation to it."""
    catalogue = catalogue_for([server(), server(slug="crm", name="CRM")])

    for tool in catalogue:
        if tool.kind is ToolKind.MCP:
            assert tool.enabled_by_default is False


# --- what the configuration refuses ---------------------------------------


def test_the_category_list_has_not_drifted_from_the_enum():
    """`config` spells the categories out rather than importing them, because
    the models package imports config back. This is what keeps that safe."""
    from typing import get_args

    from app.core.config import ToolCategoryName

    assert set(get_args(ToolCategoryName)) == {c.value for c in ToolCategory}


def test_a_credential_is_named_never_carried():
    declared = set(McpServerConfig.model_fields)

    for leak in ("token", "api_key", "secret", "password", "authorization"):
        assert leak not in declared, (
            f"McpServerConfig.{leak} would put a credential in a settings object "
            "that is logged on boot and copied into every worker."
        )
    assert "auth_ref" in declared


def test_a_credential_that_is_named_but_unset_is_a_boot_error(monkeypatch):
    monkeypatch.delenv("WIKI_TOKEN", raising=False)

    with pytest.raises(PydanticValidationError, match="that variable is unset"):
        settings_with(
            [
                {
                    "slug": "wiki",
                    "name": "Wiki",
                    "url": "https://w.example/mcp",
                    "auth_ref": "WIKI_TOKEN",
                }
            ]
        )


def test_a_duplicate_slug_is_a_boot_error():
    """One would silently shadow the other."""
    with pytest.raises(PydanticValidationError, match="more than once"):
        settings_with(
            [
                {"slug": "wiki", "name": "A", "url": "https://a.example/mcp"},
                {"slug": "wiki", "name": "B", "url": "https://b.example/mcp"},
            ]
        )


def test_plaintext_is_refused_in_production_because_the_token_is_on_the_wire():
    with pytest.raises(PydanticValidationError, match="must use https"):
        Settings(
            app_env="production",
            secret_key="x" * 48,
            storage_backend="s3",
            s3_access_key_id="k",
            s3_secret_access_key="s",
            embedding_provider="openai",
            openai_api_key="k",
            sandbox_backend="http",
            sandbox_auth_token="t",
            mcp_servers=[McpServerConfig(slug="wiki", name="W", url="http://w.example/mcp")],
        )


def test_a_slug_the_model_could_not_be_shown_is_refused():
    """Slugs become part of the tool name, which vendors constrain."""
    for bad in ("Wiki", "wiki server", "wiki/../etc", "w" * 60, ""):
        with pytest.raises(PydanticValidationError):
            McpServerConfig(slug=bad, name="W", url="https://w.example/mcp")


def test_a_url_that_is_not_absolute_http_is_refused():
    for bad in ("file:///etc/passwd", "wiki.example.com", "ftp://w.example"):
        with pytest.raises(PydanticValidationError):
            McpServerConfig(slug="wiki", name="W", url=bad)


def test_servers_are_read_from_the_environment_as_json(monkeypatch):
    """The whole delivery mechanism: a config row, not a deployment."""
    monkeypatch.setenv(
        "MCP_SERVERS",
        json.dumps([{"slug": "wiki", "name": "Wiki", "url": "https://w.example/mcp"}]),
    )
    monkeypatch.setenv("APP_ENV", "test")

    parsed = Settings()

    assert [s.slug for s in parsed.mcp_servers] == ["wiki"]
