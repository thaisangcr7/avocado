"""Incrementally sync a local folder into an Avocado workspace.

This is a connector-style bridge for local files: authenticate through the
public API, scope all actions to one workspace, upload only new or changed
files, and optionally delete files in Avocado that were removed locally.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

DEFAULT_BASE_URL = os.environ.get("AVOCADO_API_BASE_URL", "http://127.0.0.1:8000")
STATE_FILENAME = ".avocado-sync-state.json"
SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".csv",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}


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

    def request(self, method: str, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        headers = dict(kwargs.get("headers") or {})
        data: bytes | None = None

        if (json_body := kwargs.get("json")) is not None:
            data = json.dumps(json_body).encode()
            headers.setdefault("Content-Type", "application/json")
        elif (files := kwargs.get("files")) is not None:
            data, content_type = encode_multipart(files)
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
                    _json=decode_json(text, response.headers.get("Content-Type", "")),
                )
        except urlerror.HTTPError as exc:
            raw = exc.read()
            text = raw.decode() if raw else ""
            return ApiResponse(
                status_code=exc.code,
                text=text,
                _json=decode_json(text, exc.headers.get("Content-Type", "") if exc.headers else ""),
            )

    def get(self, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs) -> ApiResponse:  # type: ignore[no-untyped-def]
        return self.request("DELETE", path, **kwargs)


def decode_json(text: str, content_type: str) -> object | None:
    if not text:
        return None
    if "json" not in content_type.lower() and not text.lstrip().startswith(("{", "[")):
        return None
    return json.loads(text)


def encode_multipart(files) -> tuple[bytes, str]:  # type: ignore[no-untyped-def]
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"managed_files": {}}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return {"managed_files": {}}
    managed = data.get("managed_files")
    if not isinstance(managed, dict):
        return {"managed_files": {}}
    return data


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return "text/plain"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"


def discover_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == STATE_FILENAME:
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        files.append(path)
    files.sort()
    return files


def as_relative_filename(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def request_json(client: ApiClient, method: str, path: str, *, expected: int | None = None, **kwargs):
    response = client.request(method, path, **kwargs)
    if expected is not None and response.status_code != expected:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    body = response.json()
    if not isinstance(body, (dict, list)):
        raise RuntimeError(f"{method} {path} returned non-JSON content.")
    return body


def auth_headers(client: ApiClient, email: str, password: str) -> dict[str, str]:
    login = request_json(
        client,
        "POST",
        "/auth/login",
        expected=200,
        json={"email": email, "password": password},
    )
    if not isinstance(login, dict):
        raise RuntimeError("Login response was not JSON.")
    token = login.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Login response did not include an access token.")
    return {"Authorization": f"Bearer {token}"}


def resolve_workspace_id(client: ApiClient, headers: dict[str, str], workspace_id: str | None, workspace_name: str | None) -> str:
    if workspace_id:
        return workspace_id
    if not workspace_name:
        raise RuntimeError("Provide either --workspace-id or --workspace-name.")
    workspaces = request_json(client, "GET", "/workspaces", headers=headers)
    if not isinstance(workspaces, list):
        raise RuntimeError("Workspace list response was not JSON array.")
    matches = [w for w in workspaces if isinstance(w, dict) and w.get("name") == workspace_name]
    if not matches:
        raise RuntimeError(f"Workspace named '{workspace_name}' was not found.")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple workspaces named '{workspace_name}'. Use --workspace-id.")
    resolved = matches[0].get("id")
    if not isinstance(resolved, str):
        raise RuntimeError("Workspace response did not contain a valid id.")
    return resolved


def list_documents(client: ApiClient, headers: dict[str, str], workspace_id: str) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    while True:
        suffix = f"?limit=100&cursor={cursor}" if cursor else "?limit=100"
        page = request_json(client, "GET", f"/workspaces/{workspace_id}/documents{suffix}", headers=headers)
        if not isinstance(page, dict):
            raise RuntimeError("Document list response was not JSON object.")
        batch = page.get("items")
        if not isinstance(batch, list):
            raise RuntimeError("Document list response did not contain items.")
        for item in batch:
            if isinstance(item, dict):
                items.append(item)
        next_cursor = page.get("next_cursor")
        has_more = bool(page.get("has_more"))
        if not has_more or not isinstance(next_cursor, str):
            break
        cursor = next_cursor
    return items


def wait_ready(client: ApiClient, headers: dict[str, str], document_id: str, timeout_seconds: int) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/documents/{document_id}", headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Document lookup failed: {response.status_code} {response.text}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Document lookup returned non-JSON body.")
        status = body.get("status")
        if isinstance(status, str) and status in {"ready", "failed"}:
            return status
        time.sleep(0.3)
    return "timeout"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="Local folder to sync")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Avocado base URL (with or without /api/v1)")
    parser.add_argument("--email", required=True, help="Avocado account email")
    parser.add_argument("--password", required=True, help="Avocado account password")
    parser.add_argument("--workspace-id", help="Target workspace id")
    parser.add_argument("--workspace-name", help="Target workspace name (used when workspace-id is omitted)")
    parser.add_argument("--state-file", help="Path for sync state JSON (default: <folder>/.avocado-sync-state.json)")
    parser.add_argument("--delete-missing", action="store_true", help="Delete previously synced docs that no longer exist locally")
    parser.add_argument("--wait-ready", action="store_true", help="Wait for each uploaded document to reach ready/failed")
    parser.add_argument("--ready-timeout-seconds", type=int, default=120, help="Per-document wait timeout when --wait-ready is enabled")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without mutating remote documents")
    args = parser.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Folder not found: {root}")

    state_path = Path(args.state_file).expanduser().resolve() if args.state_file else root / STATE_FILENAME
    state = load_state(state_path)
    managed_files = state.setdefault("managed_files", {})
    if not isinstance(managed_files, dict):
        raise RuntimeError("State file is invalid: managed_files must be an object.")

    base_url = normalize_base_url(args.base_url)
    client = ApiClient(base_url)
    headers = auth_headers(client, args.email, args.password)
    workspace_id = resolve_workspace_id(client, headers, args.workspace_id, args.workspace_name)

    remote_documents = list_documents(client, headers, workspace_id)
    remote_by_name: dict[str, list[dict]] = {}
    for document in remote_documents:
        filename = document.get("filename")
        if isinstance(filename, str):
            remote_by_name.setdefault(filename, []).append(document)

    discovered = discover_files(root)
    local_filenames = set()
    upload_actions: list[tuple[str, Path, str]] = []

    for path in discovered:
        relative_filename = as_relative_filename(root, path)
        local_filenames.add(relative_filename)
        digest = sha256_file(path)
        size_bytes = path.stat().st_size
        previous = managed_files.get(relative_filename)
        previous_sha = previous.get("sha256") if isinstance(previous, dict) else None
        if previous_sha == digest and relative_filename in remote_by_name:
            continue
        upload_actions.append((relative_filename, path, digest))
        managed_files[relative_filename] = {
            "sha256": digest,
            "size_bytes": size_bytes,
            "updated_at": int(time.time()),
        }

    delete_actions: list[tuple[str, str]] = []
    if args.delete_missing:
        stale_filenames = [name for name in managed_files.keys() if name not in local_filenames]
        for stale in stale_filenames:
            for document in remote_by_name.get(stale, []):
                doc_id = document.get("id")
                if isinstance(doc_id, str):
                    delete_actions.append((stale, doc_id))
            managed_files.pop(stale, None)

    print(f"Workspace: {workspace_id}")
    print(f"Folder: {root}")
    print(f"Discovered files: {len(discovered)}")
    print(f"Upload actions: {len(upload_actions)}")
    print(f"Delete actions: {len(delete_actions)}")

    if args.dry_run:
        for filename, _, _ in upload_actions:
            print(f"[dry-run] upload {filename}")
        for filename, doc_id in delete_actions:
            print(f"[dry-run] delete {filename} ({doc_id})")
        return

    for filename, doc_id in delete_actions:
        response = client.delete(f"/documents/{doc_id}", headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"Delete failed for {filename}: {response.status_code} {response.text}")
        print(f"Deleted {filename}")

    for filename, path, digest in upload_actions:
        # Keep one live document per synced filename by removing old copies.
        for document in remote_by_name.get(filename, []):
            old_id = document.get("id")
            if isinstance(old_id, str):
                response = client.delete(f"/documents/{old_id}", headers=headers)
                if response.status_code >= 400:
                    raise RuntimeError(f"Delete before upload failed for {filename}: {response.status_code} {response.text}")

        data = path.read_bytes()
        response = client.post(
            f"/workspaces/{workspace_id}/documents",
            headers=headers,
            files={"file": (filename, io.BytesIO(data), guess_content_type(path))},
        )
        if response.status_code != 201:
            raise RuntimeError(f"Upload failed for {filename}: {response.status_code} {response.text}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Upload response was not JSON for {filename}.")
        document = body.get("document")
        document_id = document.get("id") if isinstance(document, dict) else None
        if not isinstance(document_id, str):
            raise RuntimeError(f"Upload response for {filename} did not include document id.")

        managed_files[filename] = {
            "sha256": digest,
            "document_id": document_id,
            "size_bytes": len(data),
            "updated_at": int(time.time()),
        }
        print(f"Uploaded {filename}")

        if args.wait_ready:
            status = wait_ready(client, headers, document_id, args.ready_timeout_seconds)
            print(f"  -> status: {status}")

    state["workspace_id"] = workspace_id
    state["folder"] = str(root)
    state["base_url"] = base_url
    state["updated_at"] = int(time.time())
    save_state(state_path, state)
    print(f"State file: {state_path}")
    print("Sync complete.")


if __name__ == "__main__":
    main()
