"""Project and task data access, including the task visibility rule.

Architecture §11 is explicit that task visibility is **not** document
visibility: everyone in a workspace can typically read every document, but a
task assigned to one person is not workspace-public just because it lives in a
shared workspace.

So a task is visible to:

* its assignee,
* members of its project,
* `team_admin` / `org_admin`,
* everyone in the workspace, but only when the project has opted in to
  `WORKSPACE` visibility.

That rule is expressed once, as a SQL predicate, and every task query applies
it. Filtering rows in Python after loading them would be a different and much
worse thing: the rows would already have crossed the boundary, and any query
that forgot the filter would leak silently.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, true

from app.models.enums import ProjectStatus, ProjectVisibility, TaskStatus
from app.models.projects import Project, ProjectMember, Task
from app.repositories.base import WorkspaceScopedRepository


def task_visibility_predicate(user_id: uuid.UUID, *, is_admin: bool) -> ColumnElement[bool]:
    """The SQL form of "may this user see this task?".

    Admins see everything within a workspace they already have access to —
    workspace scoping is applied separately and always.
    """
    if is_admin:
        return true()

    member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    open_projects = select(Project.id).where(Project.visibility == ProjectVisibility.WORKSPACE)

    return or_(
        Task.assignee_id == user_id,
        Task.project_id.in_(member_projects),
        Task.project_id.in_(open_projects),
    )


def project_visibility_predicate(user_id: uuid.UUID, *, is_admin: bool) -> ColumnElement[bool]:
    """The same rule at project level.

    A project is listable if it is workspace-visible, if the user belongs to
    it, or if they created it. Being assigned a task inside it also counts —
    otherwise someone could hold a task in a project they cannot see, which
    makes the task impossible to reach from the UI.
    """
    if is_admin:
        return true()

    membership = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    assigned = select(Task.project_id).where(Task.assignee_id == user_id)

    return or_(
        Project.visibility == ProjectVisibility.WORKSPACE,
        Project.id.in_(membership),
        Project.id.in_(assigned),
        Project.created_by == user_id,
    )


class ProjectRepository(WorkspaceScopedRepository[Project]):
    model = Project

    def _visible(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, *, is_admin: bool
    ) -> Select[tuple[Project]]:
        return self._scoped_select(workspace_id).where(
            project_visibility_predicate(user_id, is_admin=is_admin)
        )

    async def get_visible(
        self,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        is_admin: bool,
    ) -> Project | None:
        stmt = self._visible(workspace_id, user_id, is_admin=is_admin).where(
            Project.id == project_id
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_visible(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        is_admin: bool,
        status: ProjectStatus | None = None,
    ) -> list[Project]:
        stmt = self._visible(workspace_id, user_id, is_admin=is_admin)
        if status is not None:
            stmt = stmt.where(Project.status == status)
        stmt = stmt.order_by(Project.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def member_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add_member(self, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        existing = await self._session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if existing.scalars().first() is None:
            self._session.add(ProjectMember(project_id=project_id, user_id=user_id))
            await self._session.flush()

    async def remove_member(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        row = (
            (
                await self._session.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def task_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(Task.status, func.count())
            .where(Task.project_id == project_id)
            .group_by(Task.status)
        )
        rows = (await self._session.execute(stmt)).all()
        counts = {status.value: 0 for status in TaskStatus}
        for status, count in rows:
            counts[status.value] = count
        return counts


class TaskRepository(WorkspaceScopedRepository[Task]):
    model = Task

    def _visible(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, *, is_admin: bool
    ) -> Select[tuple[Task]]:
        return self._scoped_select(workspace_id).where(
            task_visibility_predicate(user_id, is_admin=is_admin)
        )

    async def get_visible(
        self,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        is_admin: bool,
    ) -> Task | None:
        stmt = self._visible(workspace_id, user_id, is_admin=is_admin).where(Task.id == task_id)
        return (await self._session.execute(stmt)).scalars().first()

    async def list_visible(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        is_admin: bool,
        project_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        stmt = self._visible(workspace_id, user_id, is_admin=is_admin)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        if assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == assignee_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)

        # Soonest deadline first, undated last — a board is read in order of
        # what is about to bite.
        stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def due_for_user(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, *, through: date
    ) -> list[Task]:
        """Unfinished tasks assigned to this user, due on or before a date.

        No visibility predicate: these are the user's *own* tasks, and being
        the assignee is itself the strongest visibility grant there is.
        """
        stmt = (
            self._scoped_select(workspace_id)
            .where(
                Task.assignee_id == user_id,
                Task.status.notin_([TaskStatus.DONE]),
                and_(Task.due_date.is_not(None), Task.due_date <= through),
            )
            .order_by(Task.due_date.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def blocked_for_user(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Task]:
        stmt = self._scoped_select(workspace_id).where(
            Task.assignee_id == user_id, Task.status == TaskStatus.BLOCKED
        )
        return list((await self._session.execute(stmt)).scalars().all())
