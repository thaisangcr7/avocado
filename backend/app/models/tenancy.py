"""Organization / team / user / workspace — the tenancy spine.

Every tenant-scoped table hangs off `Workspace`, and every repository query
filters on `workspace_id`. The multi-tenant surface is built into the schema
from the start even though phase 1 runs a single tenant: retrofitting a tenant
column onto populated tables is far more expensive than carrying it early.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Role


def _email_col():
    """Deferred column reference for the functional index below."""
    from sqlalchemy import column

    return column("email")


def role_enum() -> Enum:
    return Enum(Role, name="role", values_callable=lambda e: [m.value for m in e])


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    plan_tier: Mapped[str] = mapped_column(String(50), nullable=False, default="free")

    teams: Mapped[list[Team]] = relationship(back_populates="organization")
    users: Mapped[list[User]] = relationship(back_populates="organization")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_users_org_email"),
        # Email identifies an account globally and case-insensitively, because
        # that is what login already assumes: it looks a user up by lowercased
        # email with no organization, so two rows matching one address make
        # login raise rather than authenticate. The per-org constraint above is
        # kept as a narrower guard; this one is what actually holds.
        #
        # The consequence is deliberate: one account per email address across
        # the whole system. Letting one person belong to two organizations with
        # the same address would require choosing an organization at login.
        Index("uq_users_email_lower", func.lower(_email_col()), unique=True),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))

    # Null when the account is provisioned by an external IdP rather than a
    # local password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    auth_provider_id: Mapped[str | None] = mapped_column(String(255), index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped[Organization] = relationship(back_populates="users")
    memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Team(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_teams_org_name"),)

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))

    organization: Mapped[Organization] = relationship(back_populates="teams")
    memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="team")


class TeamMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_user"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(role_enum(), nullable=False, default=Role.MEMBER)

    team: Mapped[Team] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workspaces"

    team_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))

    # Null means "Auto" — the ModelRouter picks per request. A concrete model
    # id here pins every request in the workspace to that model.
    preferred_model: Mapped[str | None] = mapped_column(String(100))

    team: Mapped[Team] = relationship(back_populates="workspaces")
