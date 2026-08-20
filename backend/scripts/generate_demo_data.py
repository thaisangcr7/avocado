"""Generate a realistic Avocado demo dataset through the public API.

The seed creates a small organization, a team, multiple workspaces, a
collaborator, projects, tasks, and a document set large enough to exercise the
retrieval and analysis paths the way a real team would.

One workspace is left empty on purpose so the honest no-results response can
be demonstrated instead of guessed at.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import random
import re
import shutil
import string
import textwrap
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

DEFAULT_BASE_URL = os.environ.get("AVOCADO_API_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / ".demo-data" / "latest"

OWNER_ORG = "Northwind Demo"
TEAM_NAME = "Northwind Operations"
TEAM_DESCRIPTION = "Synthetic sample team for Avocado demos and tests."
OWNER_FULL_NAME = "Northwind Owner"
COLLABORATOR_FULL_NAME = "Northwind Collaborator"


@dataclass(slots=True)
class GeneratedFile:
    workspace_key: str
    category: str
    local_path: Path
    filename: str
    content_type: str
    data: bytes


@dataclass(slots=True)
class ApiResponse:
    status_code: int
    text: str
    _json: object | None = None

    def json(self) -> object | None:
        return self._json


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def request(self, method: str, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        headers = dict(kwargs.get("headers") or {})
        data: bytes | None = None

        if (json_body := kwargs.get("json")) is not None:
            data = json.dumps(json_body).encode()
            headers.setdefault("Content-Type", "application/json")
        elif (files := kwargs.get("files")) is not None:
            data, content_type = _encode_multipart(files)
            headers.setdefault("Content-Type", content_type)

        req = urlrequest.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlrequest.urlopen(req, timeout=120) as response:
                raw = response.read()
                text = raw.decode()
                return ApiResponse(
                    status_code=response.status,
                    text=text,
                    _json=_decode_json(text, response.headers.get("Content-Type", "")),
                )
        except urlerror.HTTPError as exc:
            raw = exc.read()
            text = raw.decode() if raw else ""
            return ApiResponse(
                status_code=exc.code,
                text=text,
                _json=_decode_json(text, exc.headers.get("Content-Type", "") if exc.headers else ""),
            )

    async def get(self, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        return await self.request("POST", path, **kwargs)


def _decode_json(text: str, content_type: str) -> object | None:
    if not text:
        return None
    if "json" not in content_type.lower() and not text.lstrip().startswith(("{", "[")):
        return None
    return json.loads(text)


def _encode_multipart(files) -> tuple[bytes, str]:  # type: ignore[no-untyped-def]
    boundary = f"----avocado-{uuid.uuid4().hex}"
    body = bytearray()
    for field_name, value in files.items():
        filename, fileobj, content_type = value
        content = fileobj.read() if hasattr(fileobj, "read") else bytes(fileobj)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def normalize_base_url(raw: str) -> str:
    raw = raw.rstrip("/")
    return raw if raw.endswith("/api/v1") else f"{raw}/api/v1"


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return cleaned.strip("-") or "workspace"


def strong_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    rng = random.SystemRandom()
    return "".join(rng.choice(alphabet) for _ in range(20))


def format_markdown(title: str, sections: list[tuple[str, str]]) -> str:
    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(textwrap.fill(body, width=92))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_policy_doc(workspace_name: str, subject: str, rng: random.Random) -> str:
    effective = (date.today() - timedelta(days=rng.randint(14, 150))).isoformat()
    return format_markdown(
        f"{subject} policy",
        [
            (
                "Purpose",
                f"This policy describes how the {workspace_name} team handles {subject.lower()} so the same answer is available to every member.",
            ),
            (
                "Rules",
                f"Requests that touch {subject.lower()} should be recorded in the workspace, approved by the owner or a team admin, and reviewed again after the change is complete.",
            ),
            (
                "Examples",
                f"A {subject.lower()} exception should include the requestor, the reason, the decision, and the follow-up date.",
            ),
            ("Effective Date", f"This policy takes effect on {effective} and remains active until replaced."),
        ],
    )


def build_process_doc(workspace_name: str, process_name: str, rng: random.Random) -> str:
    reviewer = rng.choice(["operations", "finance", "customer success", "product"])
    return format_markdown(
        f"{process_name} process",
        [
            (
                "Overview",
                f"The {process_name.lower()} process keeps the {workspace_name} workspace aligned when work moves from planning to execution.",
            ),
            (
                "Steps",
                " ".join(
                    [
                        "1. Capture the request in the workspace.",
                        f"2. Review dependencies with {reviewer} before work starts.",
                        "3. Record milestones as they happen.",
                        "4. Close the loop with the result and next step.",
                    ]
                ),
            ),
            (
                "Notes",
                "If the process stalls, record the reason in the workspace instead of relying on memory.",
            ),
        ],
    )


def build_meeting_notes_doc(workspace_name: str, topic: str, rng: random.Random) -> str:
    attendees = ", ".join(rng.sample(["Avery", "Morgan", "Riley", "Jordan", "Taylor", "Casey"], 3))
    return format_markdown(
        f"{topic} meeting notes",
        [
            ("Attendees", f"{attendees} met in the {workspace_name} workspace to review the current plan."),
            (
                "Discussion",
                f"The team discussed {topic.lower()}, the blocker, the delivery sequence, and what should be surfaced to the rest of the team.",
            ),
            ("Decisions", "Keep the scope, update the owner list, and add a short daily note until the next milestone is reached."),
            ("Next Steps", "Send the recap, update the board, and make the decision visible in the workspace."),
        ],
    )


def build_context_note(workspace_name: str) -> str:
    return textwrap.dedent(
        f"""
        {workspace_name} overview

        This workspace is intentionally full of mixed document types so search,
        suggestions, task resumption, and spreadsheet analysis can all be exercised
        against the same tenant context.
        """
    ).strip() + "\n"


def write_csv(rows: list[dict[str, object]], fieldnames: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def build_revenue_csv(rng: random.Random, rows: int) -> bytes:
    regions = ["North", "South", "East", "West"]
    months = [f"2025-{month:02d}" for month in range(1, 7)]
    data = []
    for index in range(rows):
        revenue = 26000 + (index % 19) * 800 + rng.randint(-1200, 1600)
        data.append(
            {
                "month": months[index % len(months)],
                "region": regions[index % len(regions)],
                "revenue": max(12000, revenue),
                "orders": max(100, int(revenue / 175) + rng.randint(-10, 12)),
                "return_rate": round(rng.uniform(0.01, 0.07), 3),
            }
        )
    return write_csv(data, ["month", "region", "revenue", "orders", "return_rate"])


def build_support_csv(rng: random.Random, rows: int) -> bytes:
    queues = ["billing", "product", "ops", "onboarding"]
    severities = ["low", "medium", "high"]
    data = []
    for index in range(rows):
        data.append(
            {
                "week": f"2025-W{(index % 26) + 1:02d}",
                "queue": queues[index % len(queues)],
                "severity": severities[index % len(severities)],
                "opened": 40 + (index % 11) * 3 + rng.randint(0, 14),
                "closed": 28 + (index % 9) * 3 + rng.randint(0, 12),
                "age_days": rng.randint(0, 21),
            }
        )
    return write_csv(data, ["week", "queue", "severity", "opened", "closed", "age_days"])


def build_budget_csv(rng: random.Random, rows: int) -> bytes:
    categories = ["travel", "software", "contractors", "events"]
    data = []
    for index in range(rows):
        budget = 15000 + (index % 9) * 1800 + rng.randint(-500, 900)
        spent = max(5000, budget - rng.randint(-1500, 3200))
        data.append(
            {
                "month": f"2025-{(index % 12) + 1:02d}",
                "category": categories[index % len(categories)],
                "budget": budget,
                "spent": spent,
                "variance": spent - budget,
            }
        )
    return write_csv(data, ["month", "category", "budget", "spent", "variance"])


def build_forecast_csv(rng: random.Random, rows: int) -> bytes:
    scenarios = ["base", "upside", "downside"]
    data = []
    for index in range(rows):
        revenue = 50000 + (index % 14) * 2200 + rng.randint(-1200, 2500)
        expense = 28000 + (index % 10) * 1400 + rng.randint(-1000, 1800)
        data.append(
            {
                "month": f"2025-{(index % 12) + 1:02d}",
                "scenario": scenarios[index % len(scenarios)],
                "revenue": revenue,
                "expense": expense,
                "margin": revenue - expense,
            }
        )
    return write_csv(data, ["month", "scenario", "revenue", "expense", "margin"])


def build_pipeline_csv(rng: random.Random, rows: int) -> bytes:
    roles = ["engineer", "designer", "analyst", "ops"]
    stages = ["screen", "interview", "exercise", "offer"]
    data = []
    for index in range(rows):
        data.append(
            {
                "week": f"2025-W{(index % 24) + 1:02d}",
                "role": roles[index % len(roles)],
                "stage": stages[index % len(stages)],
                "candidates": 6 + (index % 5) + rng.randint(0, 4),
                "hired": rng.randint(0, 3),
                "dropoff_rate": round(rng.uniform(0.1, 0.55), 3),
            }
        )
    return write_csv(data, ["week", "role", "stage", "candidates", "hired", "dropoff_rate"])


def build_capacity_csv(rng: random.Random, rows: int) -> bytes:
    teams = ["platform", "ops", "finance", "growth"]
    data = []
    for index in range(rows):
        planned = 120 + (index % 8) * 8 + rng.randint(-10, 18)
        delivered = max(40, planned - rng.randint(5, 28))
        data.append(
            {
                "sprint": f"2025-S{(index % 12) + 1:02d}",
                "team": teams[index % len(teams)],
                "planned_hours": planned,
                "delivered_hours": delivered,
                "blocked_hours": rng.randint(0, 12),
            }
        )
    return write_csv(data, ["sprint", "team", "planned_hours", "delivered_hours", "blocked_hours"])


@dataclass(slots=True)
class WorkspaceBlueprint:
    key: str
    name: str
    description: str
    populated: bool


def build_files_for_workspace(blueprint: WorkspaceBlueprint, output_dir: Path, rows_per_csv: int) -> list[GeneratedFile]:
    if not blueprint.populated:
        return []

    rng = random.Random(blueprint.key)
    docs_dir = output_dir / blueprint.key / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    documents: list[tuple[str, str, str]] = [
        ("employee-handbook.md", "policy", build_policy_doc(blueprint.name, "Employee handbook", rng)),
        ("incident-response.md", "process", build_process_doc(blueprint.name, "Incident response", rng)),
        ("meeting-notes.md", "notes", build_meeting_notes_doc(blueprint.name, "Quarterly retrospective", rng)),
        ("workspace-context.txt", "notes", build_context_note(blueprint.name)),
    ]

    csv_builders = [
        (
            "budget_forecast.csv" if "finance" in blueprint.key else "revenue_by_region.csv",
            build_budget_csv if "finance" in blueprint.key else build_revenue_csv,
        ),
        ("support_backlog.csv", build_support_csv),
        ("hiring_pipeline.csv", build_pipeline_csv),
        ("project_capacity.csv", build_capacity_csv),
        ("forecast.csv", build_forecast_csv),
    ]

    files: list[GeneratedFile] = []
    for filename, category, content in documents:
        path = docs_dir / filename
        data = content.encode()
        path.write_bytes(data)
        files.append(
            GeneratedFile(
                workspace_key=blueprint.key,
                category=category,
                local_path=path,
                filename=filename,
                content_type="text/markdown" if filename.endswith(".md") else "text/plain",
                data=data,
            )
        )

    for filename, builder in csv_builders:
        path = docs_dir / filename
        data = builder(rng, rows_per_csv)
        path.write_bytes(data)
        files.append(
            GeneratedFile(
                workspace_key=blueprint.key,
                category="analysis",
                local_path=path,
                filename=filename,
                content_type="text/csv",
                data=data,
            )
        )

    return files


def _decode_json(text: str, content_type: str) -> object | None:
    if not text:
        return None
    if "json" not in content_type.lower() and not text.lstrip().startswith(("{", "[")):
        return None
    return json.loads(text)


def _encode_multipart(files) -> tuple[bytes, str]:  # type: ignore[no-untyped-def]
    boundary = f"----avocado-{uuid.uuid4().hex}"
    body = bytearray()
    for field_name, value in files.items():
        filename, fileobj, content_type = value
        content = fileobj.read() if hasattr(fileobj, "read") else bytes(fileobj)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


async def request_json(client: ApiClient, method: str, path: str, *, expected: int | None = None, **kwargs):
    response = await client.request(method, path, **kwargs)
    if expected is not None and response.status_code != expected:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    body = response.json()
    if not isinstance(body, (dict, list)):
        raise RuntimeError(f"{method} {path} returned non-JSON content.")
    return body


async def register_owner(client: ApiClient, email: str, password: str) -> dict:
    await request_json(
        client,
        "POST",
        "/auth/register",
        expected=201,
        json={
            "email": email,
            "password": password,
            "full_name": OWNER_FULL_NAME,
            "organization_name": OWNER_ORG,
        },
    )
    login = await request_json(client, "POST", "/auth/login", expected=200, json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    me = await request_json(client, "GET", "/auth/me", headers=headers)
    return {"email": email, "password": password, "headers": headers, "me": me, "tokens": login}


async def invite_collaborator(client: ApiClient, owner: dict, team_id: str) -> dict:
    email = f"collaborator-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        f"/teams/{team_id}/invitations",
        headers=owner["headers"],
        json={"email": email, "role": "member", "expires_in_days": 14},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Invitation creation failed: {response.status_code} {response.text}")
    invite = response.json()
    if not isinstance(invite, dict):
        raise RuntimeError("Invitation response was not JSON.")

    password = f"AvocadoDemo!{uuid.uuid4().hex[:6]}"
    accept = await request_json(
        client,
        "POST",
        f"/invitations/{invite['token']}/accept",
        expected=200,
        json={"password": password, "full_name": COLLABORATOR_FULL_NAME},
    )
    headers = {"Authorization": f"Bearer {accept['access_token']}"}
    me = await request_json(client, "GET", "/auth/me", headers=headers)
    return {"email": email, "password": password, "headers": headers, "me": me, "invite": invite, "tokens": accept}


async def create_workspace(client: ApiClient, owner: dict, team_id: str, name: str, description: str) -> dict:
    return await request_json(
        client,
        "POST",
        "/workspaces",
        expected=201,
        headers=owner["headers"],
        json={"name": name, "description": description, "team_id": team_id, "preferred_model": None},
    )


async def upload_document(client: ApiClient, owner: dict, workspace_id: str, file: GeneratedFile) -> dict:
    response = await client.post(
        f"/workspaces/{workspace_id}/documents",
        headers=owner["headers"],
        files={"file": (file.filename, io.BytesIO(file.data), file.content_type)},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Upload failed for {file.filename}: {response.status_code} {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Upload response was not JSON.")
    return body


async def wait_for_document(client: ApiClient, owner: dict, document_id: str, attempts: int = 180) -> dict:
    for _ in range(attempts):
        response = await client.get(f"/documents/{document_id}", headers=owner["headers"])
        if response.status_code != 200:
            raise RuntimeError(f"Document lookup failed: {response.status_code} {response.text}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Document response was not JSON.")
        if body["status"] in {"ready", "failed"}:
            return body
        await asyncio.sleep(0.2)
    raise RuntimeError(f"Document {document_id} did not finish processing.")


async def create_project(
    client: ApiClient,
    owner: dict,
    workspace_id: str,
    name: str,
    goal: str,
    member_ids: list[str],
) -> dict:
    return await request_json(
        client,
        "POST",
        f"/workspaces/{workspace_id}/projects",
        expected=201,
        headers=owner["headers"],
        json={"name": name, "goal": goal, "visibility": "restricted", "member_ids": member_ids},
    )


async def create_task(
    client: ApiClient,
    owner: dict,
    workspace_id: str,
    project_id: str,
    title: str,
    notes: str,
    assignee_id: str,
    due_date: str,
    status: str = "todo",
) -> dict:
    return await request_json(
        client,
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/tasks",
        expected=201,
        headers=owner["headers"],
        json={
            "title": title,
            "notes": notes,
            "assignee_id": assignee_id,
            "status": status,
            "due_date": due_date,
        },
    )


async def create_conversation(client: ApiClient, owner: dict, workspace_id: str, title: str) -> dict:
    return await request_json(
        client,
        "POST",
        f"/workspaces/{workspace_id}/conversations",
        expected=201,
        headers=owner["headers"],
        json={"title": title},
    )


async def ask_question(client: ApiClient, owner: dict, workspace_id: str, conversation_id: str, question: str) -> dict:
    response = await client.post(
        f"/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        headers=owner["headers"],
        json={"content": question},
    )
    if response.status_code != 201:
        raise RuntimeError(f"Question failed: {response.status_code} {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Question response was not JSON.")
    return body


def build_manifest_path(output_dir: Path) -> Path:
    return output_dir / "manifest.json"


def reset_local_database() -> None:
    container_result = subprocess.run(
        ["docker", "ps", "--filter", "name=avocado-db", "--format", "{{.Names}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    container_name = next((line.strip() for line in container_result.stdout.splitlines() if line.strip()), None)
    if container_name is None:
        raise RuntimeError("Could not find the running avocado-db container. Start the compose stack first.")

    tables_result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container_name,
            "psql",
            "-U",
            "avocado",
            "-d",
            "avocado",
            "-At",
            "-c",
            "SELECT string_agg(format('%I.%I', schemaname, tablename), ', ') "
            "FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version';",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tables = tables_result.stdout.strip()
    if not tables:
        return

    truncate = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container_name,
            "psql",
            "-U",
            "avocado",
            "-d",
            "avocado",
            "-c",
            f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE;",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if truncate.returncode != 0:
        raise RuntimeError(truncate.stderr.strip() or "Reset failed.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Avocado API base URL")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated source files and manifest")
    parser.add_argument("--rows-per-csv", type=int, default=800, help="Rows to generate for each sample CSV")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear the local demo database before seeding.",
    )
    args = parser.parse_args()

    base_url = normalize_base_url(args.base_url)
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.reset:
        reset_local_database()

    blueprints = [
        WorkspaceBlueprint(slugify("Northwind HQ"), "Northwind HQ", "Operations workspace with policies and meeting notes.", True),
        WorkspaceBlueprint(slugify("Northwind Finance"), "Northwind Finance", "Finance workspace with budget and forecast data.", True),
        WorkspaceBlueprint(slugify("Northwind Sandbox"), "Northwind Sandbox", "Intentionally empty workspace for the no-results path.", False),
    ]

    files: list[GeneratedFile] = []
    for blueprint in blueprints:
        files.extend(build_files_for_workspace(blueprint, output_dir, args.rows_per_csv))

    owner_email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    owner_password = strong_password()

    manifest: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "output_dir": str(output_dir),
        "owner": {"email": owner_email, "password": owner_password},
        "blueprints": [
            {"key": b.key, "name": b.name, "description": b.description, "populated": b.populated}
            for b in blueprints
        ],
        "files": [
            {
                "workspace_key": f.workspace_key,
                "category": f.category,
                "local_path": str(f.local_path.relative_to(output_dir)),
                "filename": f.filename,
                "content_type": f.content_type,
                "size_bytes": len(f.data),
            }
            for f in files
        ],
    }

    client = ApiClient(base_url)
    owner = await register_owner(client, owner_email, owner_password)
    owner_id = owner["me"]["id"]

    teams = await request_json(client, "GET", "/teams", headers=owner["headers"])
    if not isinstance(teams, list) or not teams:
        raise RuntimeError("No team was created for the demo account.")
    team = teams[0]

    await request_json(
        client,
        "PATCH",
        f"/teams/{team['id']}",
        expected=200,
        headers=owner["headers"],
        json={"name": TEAM_NAME, "description": TEAM_DESCRIPTION},
    )

    refreshed_team = (await request_json(client, "GET", "/teams", headers=owner["headers"]))[0]

    workspaces = await request_json(client, "GET", "/workspaces", headers=owner["headers"])
    if not isinstance(workspaces, list) or not workspaces:
        raise RuntimeError("No workspace was created for the demo account.")

    default_workspace = workspaces[0]
    await request_json(
        client,
        "PATCH",
        f"/workspaces/{default_workspace['id']}",
        expected=200,
        headers=owner["headers"],
        json={"name": blueprints[0].name, "description": blueprints[0].description, "preferred_model": None},
    )
    default_workspace.update({"name": blueprints[0].name, "description": blueprints[0].description})
    populated_workspaces = [default_workspace]

    second_workspace = await create_workspace(client, owner, refreshed_team["id"], blueprints[1].name, blueprints[1].description)
    populated_workspaces.append(second_workspace)
    empty_workspace = await create_workspace(client, owner, refreshed_team["id"], blueprints[2].name, blueprints[2].description)

    collaborator = await invite_collaborator(client, owner, refreshed_team["id"])
    collaborator_id = collaborator["me"]["id"]

    uploaded_documents: list[dict[str, object]] = []
    for blueprint, workspace in zip(blueprints[:2], populated_workspaces, strict=True):
        workspace_files = [generated for generated in files if generated.workspace_key == blueprint.key]
        for file in workspace_files:
            uploaded = await upload_document(client, owner, workspace["id"], file)
            ready = await wait_for_document(client, owner, uploaded["document"]["id"])
            uploaded_documents.append(
                {
                    "workspace_key": blueprint.key,
                    "workspace_id": workspace["id"],
                    "filename": file.filename,
                    "document_id": ready["id"],
                    "status": ready["status"],
                    "chunk_count": ready["chunk_count"],
                }
            )

    project_one = await create_project(
        client,
        owner,
        populated_workspaces[0]["id"],
        "Operations launch plan",
        "Track the team launch checklist, ownership, and milestone timing.",
        [collaborator_id],
    )
    project_two = await create_project(
        client,
        owner,
        populated_workspaces[0]["id"],
        "Support backlog review",
        "Keep the customer queue and the weekly review visible to the whole team.",
        [collaborator_id],
    )
    project_three = await create_project(
        client,
        owner,
        populated_workspaces[1]["id"],
        "Budget planning",
        "Review monthly budget movements and forecast variance.",
        [owner_id],
    )

    today = date.today()
    tasks = []
    for index, project in enumerate([project_one, project_two, project_three], start=1):
        for offset in range(5):
            task = await create_task(
                client,
                owner,
                project["workspace_id"],
                project["id"],
                f"{project['name']} task {offset + 1}",
                f"Task {offset + 1} for {project['name']}. Keep the status visible in Avocado.",
                collaborator_id if index < 3 else owner_id,
                (today + timedelta(days=offset - 1)).isoformat(),
                status="in_progress" if offset == 1 else "todo",
            )
            tasks.append(task)

    empty_conversation = await create_conversation(client, owner, empty_workspace["id"], "Empty workspace smoke test")
    no_result = await ask_question(client, owner, empty_workspace["id"], empty_conversation["id"], "What is the onboarding policy?")

    stats = await request_json(client, "GET", f"/workspaces/{populated_workspaces[0]['id']}/stats", headers=owner["headers"])

    manifest.update(
        {
            "team": refreshed_team,
            "owner_user_id": owner_id,
            "collaborator": collaborator["me"],
            "workspaces": [
                {"key": blueprints[0].key, "api": populated_workspaces[0], "populated": True},
                {"key": blueprints[1].key, "api": populated_workspaces[1], "populated": True},
                {"key": blueprints[2].key, "api": empty_workspace, "populated": False},
            ],
            "documents": uploaded_documents,
            "projects": [project_one, project_two, project_three],
            "tasks_created": len(tasks),
            "empty_workspace_check": {
                "conversation_id": empty_conversation["id"],
                "answer": no_result["assistant_message"]["content"],
                "model_used": no_result["assistant_message"]["model_used"],
            },
            "workspace_stats": stats,
        }
    )

    build_manifest_path(output_dir).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Demo data created under {output_dir}")
    print(f"Owner: {manifest['owner']['email']}")
    print(f"Collaborator: {manifest['collaborator']['email']}")
    print(f"Manifest: {build_manifest_path(output_dir)}")


if __name__ == "__main__":
    asyncio.run(main())