"""Projects and tasks.

Task visibility is enforced in the repository as a SQL predicate, so this
service never filters rows itself — it passes the caller's identity down and
trusts that a row it did not receive is a row the caller may not see. That is
the point of putting the rule in the query: there is no code path here that
could forget it.
"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models.enums import ProjectStatus, Role, TaskStatus
from app.models.projects import Project, Task
from app.repositories.projects import ProjectRepository, TaskRepository
from app.schemas.projects import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from app.services.membership_service import MembershipService

log = get_logger(__name__)


class ProjectService:
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        tasks: TaskRepository,
        membership_service: MembershipService,
    ) -> None:
        self._projects = projects
        self._tasks = tasks
        self._access = membership_service

    async def is_workspace_admin(self, user_id: uuid.UUID, team_id: uuid.UUID) -> bool:
        """Whether this user administers the workspace's team.

        Admins see every task in a workspace they can already reach (§11).
        Delegated to MembershipService rather than reimplemented here: role
        resolution — including the org-admin scoping that keeps it from being a
        cross-tenant escalation — belongs in exactly one place.
        """
        role = await self._access.role_in_team(user_id, team_id)
        return role is not None and role.at_least(Role.TEAM_ADMIN)

    # --- projects ----------------------------------------------------------

    async def list_projects(
        self,
        *,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        status: ProjectStatus | None = None,
    ) -> list[ProjectResponse]:
        rows = await self._projects.list_visible(
            workspace_id,
            user_id,
            is_admin=await self.is_workspace_admin(user_id, team_id),
            status=status,
        )
        return [ProjectResponse.model_validate(p) for p in rows]

    async def create_project(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ProjectCreate,
    ) -> ProjectDetailResponse:
        project = await self._projects.add(
            Project(
                workspace_id=workspace_id,
                created_by=user_id,
                name=payload.name,
                goal=payload.goal,
                visibility=payload.visibility,
                status=ProjectStatus.ACTIVE,
            )
        )
        await self._projects.commit()

        # The creator is a member. Otherwise a restricted project could vanish
        # from its author's own list the moment it is created.
        await self._projects.add_member(project.id, user_id)
        for member_id in payload.member_ids:
            await self._projects.add_member(project.id, member_id)
        await self._projects.commit()

        log.info(
            "project_created",
            project_id=str(project.id),
            workspace_id=str(workspace_id),
            visibility=payload.visibility.value,
        )
        # Built directly rather than re-fetched: the creator is a member by
        # construction, so re-running the visibility query would only be a
        # slower way to reach the same row.
        return await self._detail(project)

    async def _detail(self, project: Project) -> ProjectDetailResponse:
        return ProjectDetailResponse(
            **ProjectResponse.model_validate(project).model_dump(),
            member_ids=await self._projects.member_ids(project.id),
            task_counts=await self._projects.task_counts(project.id),
        )

    async def get_project(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProjectDetailResponse:
        project = await self._projects.get_visible(
            project_id,
            workspace_id,
            user_id,
            is_admin=await self.is_workspace_admin(user_id, team_id),
        )
        if project is None:
            # Invisible and absent are reported identically: telling someone a
            # project exists but is not theirs is itself a disclosure.
            raise NotFoundError("Project not found.")
        return await self._detail(project)

    async def update_project(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ProjectUpdate,
    ) -> ProjectDetailResponse:
        is_admin = await self.is_workspace_admin(user_id, team_id)
        project = await self._projects.get_visible(
            project_id, workspace_id, user_id, is_admin=is_admin
        )
        if project is None:
            raise NotFoundError("Project not found.")

        await self._require_project_admin(project, user_id, is_admin=is_admin)

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        await self._projects.commit()
        await self._projects.refresh(project)
        return await self._detail(project)

    async def delete_project(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        is_admin = await self.is_workspace_admin(user_id, team_id)
        project = await self._projects.get_visible(
            project_id, workspace_id, user_id, is_admin=is_admin
        )
        if project is None:
            raise NotFoundError("Project not found.")

        await self._require_project_admin(project, user_id, is_admin=is_admin)
        await self._projects.delete(project)
        await self._projects.commit()
        log.info("project_deleted", project_id=str(project_id))

    async def add_member(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        member_id: uuid.UUID,
    ) -> None:
        is_admin = await self.is_workspace_admin(user_id, team_id)
        project = await self._projects.get_visible(
            project_id, workspace_id, user_id, is_admin=is_admin
        )
        if project is None:
            raise NotFoundError("Project not found.")
        await self._require_project_admin(project, user_id, is_admin=is_admin)

        await self._projects.add_member(project_id, member_id)
        await self._projects.commit()

    async def remove_member(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        member_id: uuid.UUID,
    ) -> None:
        is_admin = await self.is_workspace_admin(user_id, team_id)
        project = await self._projects.get_visible(
            project_id, workspace_id, user_id, is_admin=is_admin
        )
        if project is None:
            raise NotFoundError("Project not found.")
        if member_id != user_id:
            await self._require_project_admin(project, user_id, is_admin=is_admin)

        if not await self._projects.remove_member(project_id, member_id):
            raise NotFoundError("That person is not a member of this project.")
        await self._projects.commit()

    async def _require_project_admin(
        self, project: Project, user_id: uuid.UUID, *, is_admin: bool
    ) -> None:
        """Only the creator or a team admin may reshape a project.

        Membership grants sight of a project, not authority over it — otherwise
        anyone added to a board could delete it.
        """
        if is_admin or project.created_by == user_id:
            return
        raise PermissionDeniedError("Only the project's creator or a team admin can change it.")

    # --- tasks -------------------------------------------------------------

    async def list_tasks(
        self,
        *,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
    ) -> list[TaskResponse]:
        rows = await self._tasks.list_visible(
            workspace_id,
            user_id,
            is_admin=await self.is_workspace_admin(user_id, team_id),
            project_id=project_id,
            assignee_id=assignee_id,
            status=status,
        )
        return [TaskResponse.model_validate(t) for t in rows]

    async def create_task(
        self,
        *,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: TaskCreate,
    ) -> TaskResponse:
        is_admin = await self.is_workspace_admin(user_id, team_id)
        project = await self._projects.get_visible(
            project_id, workspace_id, user_id, is_admin=is_admin
        )
        if project is None:
            raise NotFoundError("Project not found.")

        task = await self._tasks.add(
            Task(
                project_id=project_id,
                workspace_id=workspace_id,
                assignee_id=payload.assignee_id,
                title=payload.title,
                notes=payload.notes,
                status=payload.status,
                due_date=payload.due_date,
            )
        )
        await self._tasks.commit()
        log.info("task_created", task_id=str(task.id), project_id=str(project_id))
        return TaskResponse.model_validate(task)

    async def get_task(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> TaskResponse:
        task = await self._require_visible_task(task_id, workspace_id, team_id, user_id)
        return TaskResponse.model_validate(task)

    async def update_task(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: TaskUpdate,
    ) -> TaskResponse:
        task = await self._require_visible_task(task_id, workspace_id, team_id, user_id)

        updates = payload.model_dump(exclude_unset=True)
        if updates.get("status") is TaskStatus.DONE and task.status is not TaskStatus.DONE:
            log.info("task_completed", task_id=str(task_id))

        for field, value in updates.items():
            setattr(task, field, value)
        await self._tasks.commit()
        await self._tasks.refresh(task)
        return TaskResponse.model_validate(task)

    async def delete_task(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        task = await self._require_visible_task(task_id, workspace_id, team_id, user_id)
        await self._tasks.delete(task)
        await self._tasks.commit()

    async def _require_visible_task(
        self,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Task:
        task = await self._tasks.get_visible(
            task_id,
            workspace_id,
            user_id,
            is_admin=await self.is_workspace_admin(user_id, team_id),
        )
        if task is None:
            raise NotFoundError("Task not found.")
        return task
