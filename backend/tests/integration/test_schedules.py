"""Schedules: a prompt that runs on its own.

The CRUD is the easy half. What matters is the executor: that a run lands in
history like any other answer, that a failure in one workspace cannot stop
another's, and that a failed schedule moves its clock forward rather than
retrying for ever on every tick.
"""

from __future__ import annotations

import datetime

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio

# Every weekday at 09:00.
CRON = "0 9 * * 1-5"


def path(account, suffix: str = "") -> str:
    return f"/workspaces/{account['workspace_id']}/schedules{suffix}"


async def make_schedule(client, account, **overrides) -> dict:
    body = {"name": "Morning brief", "prompt": "What changed overnight?", "cron": CRON}
    body.update(overrides)
    response = await client.post(path(account), json=body, headers=account["headers"])
    assert response.status_code == 201, response.text
    return response.json()


# --- the resource ---------------------------------------------------------


async def test_a_schedule_knows_when_it_next_runs(client, account):
    schedule = await make_schedule(client, account)

    assert schedule["next_run_at"] is not None
    when = datetime.datetime.fromisoformat(schedule["next_run_at"])
    assert when > datetime.datetime.now(datetime.UTC)
    assert when.hour == 9
    assert when.weekday() < 5, "0 9 * * 1-5 is weekdays only"


async def test_a_cron_that_would_never_fire_is_refused(client, account):
    """It fails silently otherwise: the schedule simply never runs and nobody
    notices for a week."""
    response = await client.post(
        path(account),
        json={"name": "Broken", "prompt": "x", "cron": "not a cron"},
        headers=account["headers"],
    )

    assert response.status_code == 422


async def test_changing_the_recurrence_moves_the_next_run(client, account):
    schedule = await make_schedule(client, account)

    updated = await client.patch(
        path(account, f"/{schedule['id']}"),
        json={"cron": "30 6 * * *"},
        headers=account["headers"],
    )

    assert updated.status_code == 200
    when = datetime.datetime.fromisoformat(updated.json()["next_run_at"])
    # Otherwise the old time stands and the edit appears to have done nothing.
    assert (when.hour, when.minute) == (6, 30)


async def test_a_schedule_can_be_disabled_without_being_deleted(client, account):
    schedule = await make_schedule(client, account)

    updated = await client.patch(
        path(account, f"/{schedule['id']}"),
        json={"enabled": False},
        headers=account["headers"],
    )

    assert updated.json()["enabled"] is False
    listed = (await client.get(path(account), headers=account["headers"])).json()
    assert [s["id"] for s in listed] == [schedule["id"]]


async def test_a_schedule_cannot_borrow_an_unreadable_preset(client, account):
    """A preset id pasted from anywhere would otherwise run somebody else's
    private instruction on a timer."""
    outsider = await register_account(client, email="sched@other.example", org="Other")
    created = await client.post(
        "/presets",
        json={"name": "Theirs", "system_prompt": "A private style."},
        headers=outsider["headers"],
    )

    response = await client.post(
        path(account),
        json={
            "name": "Borrowed",
            "prompt": "x",
            "cron": CRON,
            "preset_id": created.json()["id"],
        },
        headers=account["headers"],
    )

    assert response.status_code == 404


async def test_schedules_do_not_cross_a_workspace(client, account):
    outsider = await register_account(client, email="sched2@other.example", org="Other")
    schedule = await make_schedule(client, account)

    assert (await client.get(path(outsider), headers=outsider["headers"])).json() == []
    assert (
        await client.patch(
            f"/workspaces/{outsider['workspace_id']}/schedules/{schedule['id']}",
            json={"enabled": False},
            headers=outsider["headers"],
        )
    ).status_code == 404


# --- the executor ---------------------------------------------------------


async def due_now(app, schedule_id: str) -> None:
    """Move a schedule's clock into the past so the next sweep picks it up."""
    from sqlalchemy import text

    async with app.state.session_factory() as session:
        await session.execute(
            text("UPDATE schedules SET next_run_at = now() - interval '1 minute' WHERE id = :i"),
            {"i": schedule_id},
        )
        await session.commit()


async def sweep(app):
    from app.worker.tasks import run_due_schedules

    return await run_due_schedules(
        session_factory=app.state.session_factory,
        model_router=app.state.model_router,
        embeddings=app.state.embeddings,
    )


async def test_a_due_schedule_lands_in_history_like_any_other_answer(
    client, account, app, fake_llm
):
    """A scheduled answer is not a special kind of object — it is a
    conversation, so it is readable later with its citations."""
    schedule = await make_schedule(client, account, name="Overnight")
    await due_now(app, schedule["id"])
    fake_llm.responses = ["Nothing changed overnight."]

    fired = await sweep(app)

    assert fired == 1
    conversations = (
        await client.get(
            f"/workspaces/{account['workspace_id']}/conversations", headers=account["headers"]
        )
    ).json()
    thread = next(c for c in conversations if c["title"] == "Overnight")
    messages = (
        await client.get(
            f"/workspaces/{account['workspace_id']}/conversations/{thread['id']}/messages",
            headers=account["headers"],
        )
    ).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What changed overnight?"


async def test_a_run_moves_the_clock_forward(client, account, app, fake_llm):
    schedule = await make_schedule(client, account)
    await due_now(app, schedule["id"])
    fake_llm.responses = ["Done."]

    await sweep(app)

    after = (await client.get(path(account), headers=account["headers"])).json()[0]
    assert after["last_run_at"] is not None
    assert datetime.datetime.fromisoformat(after["next_run_at"]) > datetime.datetime.now(
        datetime.UTC
    )


async def test_a_disabled_schedule_is_not_run(client, account, app, fake_llm):
    schedule = await make_schedule(client, account, enabled=False)
    await due_now(app, schedule["id"])

    fired = await sweep(app)

    assert fired == 0


async def test_a_failing_schedule_records_why_and_still_moves_on(
    client, account, app, fake_llm, monkeypatch
):
    """A schedule that kept its old due time after failing would be retried on
    every tick for ever."""
    schedule = await make_schedule(client, account)
    await due_now(app, schedule["id"])

    from app.services.rag_service import RAGService

    async def explode(*args, **kwargs):
        raise RuntimeError("the model is on fire")

    monkeypatch.setattr(RAGService, "answer", explode)

    fired = await sweep(app)

    assert fired == 0
    after = (await client.get(path(account), headers=account["headers"])).json()[0]
    assert "on fire" in after["last_error"]
    assert datetime.datetime.fromisoformat(after["next_run_at"]) > datetime.datetime.now(
        datetime.UTC
    )


async def test_one_failing_schedule_does_not_stop_another(
    client, account, app, fake_llm, monkeypatch
):
    """Invisible, and someone else's fault: the worst possible shape for a bug."""
    first = await make_schedule(client, account, name="Breaks")
    second = await make_schedule(client, account, name="Works")
    await due_now(app, first["id"])
    await due_now(app, second["id"])

    from app.services.rag_service import RAGService

    original = RAGService.answer
    calls = {"n": 0}

    async def sometimes(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first one breaks")
        return await original(self, **kwargs)

    monkeypatch.setattr(RAGService, "answer", sometimes)
    fake_llm.responses = ["The second one still ran."]

    fired = await sweep(app)

    assert fired == 1, "the second schedule must still run"
