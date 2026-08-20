"""Keeping credentials out of logs.

An invitation token has to travel in a URL for the link to be openable, which
means the one place it can be kept out of is the log — precisely where URLs
otherwise accumulate, along with proxy history and error trackers.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.logging import REDACTED, redact_path


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/invitations/qMBwjaqma7BMRbWk6v5xaw3DUPNxm8Ais4p8Vb4RuI8",
        "/api/v1/invitations/qMBwjaqma7BMRbWk6v5xaw3DUPNxm8Ais4p8Vb4RuI8/accept",
        "/api/v1/invitations/3SDFvvoSDA85-rdXIbZIpOaFMHRZMRVxQdgD511shMk/accept",
    ],
)
def test_an_invitation_token_is_masked(path):
    redacted = redact_path(path)
    assert REDACTED in redacted
    assert "qMBwjaqma7BMRbWk6v5xaw3DUPNxm8Ais4p8Vb4RuI8" not in redacted
    assert "3SDFvvoSDA85-rdXIbZIpOaFMHRZMRVxQdgD511shMk" not in redacted


def test_the_surrounding_path_is_preserved():
    """Redaction must not destroy the route, or the log stops being useful."""
    result = redact_path("/api/v1/invitations/sometokenvalue123/accept")
    assert result == f"/api/v1/invitations/{REDACTED}/accept"


def test_an_invitation_id_is_left_alone():
    """The revoke route takes an id, not a secret — masking it would cost
    debuggability for nothing."""
    path = f"/api/v1/invitations/{uuid.uuid4()}"
    assert redact_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspaces/abc/documents",
        "/api/v1/teams/66517d14-1007-42fa-b0e9-377d195efc10/invitations",
        "/api/v1/auth/login",
        "/",
    ],
)
def test_ordinary_paths_are_untouched(path):
    assert redact_path(path) == path
