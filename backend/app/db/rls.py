"""Row-level security plumbing.

Architecture §13 asks for Postgres RLS as defence in depth. The repository
layer already scopes every query by `workspace_id`; this is the second,
independent layer, so that a query which *forgot* that filter still cannot
return another tenant's rows.

Three things make or break it, and each is silently wrong by default:

1. **The connecting role must not bypass RLS.** A superuser — and the table
   owner, unless `FORCE` is set — ignores policies entirely. Enabling RLS while
   connecting as `postgres` gives the appearance of protection and none of the
   substance. `verify_enforcement()` exists to catch exactly that.

2. **The identity must survive a commit.** Services commit constantly, and
   `SET LOCAL` dies with its transaction. So it is re-applied on every
   transaction begin via an event listener rather than set once per request.

3. **Unset must mean nothing, not everything.** `current_setting(..., true)`
   returns NULL when absent, and the policies compare against it, so a session
   that never identifies itself sees zero rows.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

# The authenticated user, and the workspace a request or job is operating on.
# Either is enough to see a row; both are optional so unauthenticated paths
# simply see nothing.
rls_user_id: ContextVar[str | None] = ContextVar("rls_user_id", default=None)
rls_workspace_id: ContextVar[str | None] = ContextVar("rls_workspace_id", default=None)

USER_SETTING = "avocado.user_id"
WORKSPACE_SETTING = "avocado.workspace_id"


def set_identity(
    *, user_id: uuid.UUID | str | None = None, workspace_id: uuid.UUID | str | None = None
) -> None:
    """Declare who the current task is acting as.

    Contextvars rather than arguments: the identity has to reach a listener
    deep inside SQLAlchemy's transaction machinery, and threading it through
    every repository call is exactly the kind of thing a call site forgets.
    """
    if user_id is not None:
        rls_user_id.set(str(user_id))
    if workspace_id is not None:
        rls_workspace_id.set(str(workspace_id))


def clear_identity() -> None:
    rls_user_id.set(None)
    rls_workspace_id.set(None)


def install_session_identity() -> None:
    """Re-apply the identity at the start of every transaction.

    Registered once, globally, against the ORM Session class. Doing this per
    request instead would lose the setting at the first commit — and the bug
    would look like "some queries mysteriously return nothing", which is a
    miserable thing to debug.
    """
    if getattr(install_session_identity, "_installed", False):
        return

    @event.listens_for(Session, "after_begin")
    def _apply_identity(session, transaction, connection):  # type: ignore[no-untyped-def]
        user = rls_user_id.get()
        workspace = rls_workspace_id.get()
        if user is None and workspace is None:
            return
        # Parameterised, not interpolated: these values originate from a token
        # and a URL path, and SET does not take bind parameters, so they go
        # through set_config() instead.
        connection.execute(
            text(
                "SELECT set_config(:user_key, :user_val, true), "
                "set_config(:ws_key, :ws_val, true)"
            ),
            {
                "user_key": USER_SETTING,
                "user_val": user or "",
                "ws_key": WORKSPACE_SETTING,
                "ws_val": workspace or "",
            },
        )

    install_session_identity._installed = True  # type: ignore[attr-defined]


async def verify_enforcement(engine) -> tuple[bool, str]:  # type: ignore[no-untyped-def]
    """Check that the connecting role actually cannot bypass RLS.

    Worth doing at startup because the failure is silent: policies can be
    enabled, forced, and completely ignored, and nothing in the application
    behaves any differently. Returns (enforced, explanation).
    """
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT current_user, "
                        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
                    )
                )
            ).one()
    except Exception as exc:
        return False, f"could not be checked ({type(exc).__name__})"

    role, is_super, bypasses = row
    if is_super:
        return False, f"role '{role}' is a superuser and ignores every policy"
    if bypasses:
        return False, f"role '{role}' has BYPASSRLS"
    return True, f"enforced for role '{role}'"
