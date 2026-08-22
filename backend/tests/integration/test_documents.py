"""Upload, validation, ingestion and the document lifecycle."""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest

pytestmark = pytest.mark.anyio

CSV_CONTENT = b"""region,month,revenue,units
North,2024-01,10000,120
North,2024-02,15000,180
South,2024-01,8000,95
South,2024-02,12000,140
"""


async def wait_for_ready(client, document_id: str, headers: dict, attempts: int = 80):
    for _ in range(attempts):
        response = await client.get(f"/documents/{document_id}", headers=headers)
        if response.status_code == 200 and response.json()["status"] in ("ready", "failed"):
            return response.json()
        await asyncio.sleep(0.05)
    raise AssertionError("Document never finished processing.")


async def upload(client, account, filename, content, content_type):
    return await client.post(
        f"/workspaces/{account['workspace_id']}/documents",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=account["headers"],
    )


async def test_text_upload_is_ingested_and_becomes_retrievable(client, account):
    response = await upload(
        client,
        account,
        "policy.txt",
        b"The remote work policy allows three days at home." * 20,
        "text/plain",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["deduplicated"] is False
    assert body["document"]["status"] == "pending"

    document = await wait_for_ready(client, body["document"]["id"], account["headers"])
    assert document["status"] == "ready", document.get("error_message")
    assert document["chunk_count"] > 0


async def test_csv_upload_produces_an_analysable_table(client, account):
    """A spreadsheet must yield both retrievable text *and* a structured table."""
    response = await upload(client, account, "sales.csv", CSV_CONTENT, "text/csv")
    assert response.status_code == 201

    document = await wait_for_ready(client, response.json()["document"]["id"], account["headers"])
    assert document["status"] == "ready", document.get("error_message")
    assert document["chunk_count"] > 0

    assert len(document["tables"]) == 1
    table = document["tables"][0]
    assert table["row_count"] == 4
    assert {c["name"] for c in table["columns"]} == {"region", "month", "revenue", "units"}


async def test_markdown_sections_become_citable_metadata(client, account):
    content = b"# Onboarding\n\nWelcome aboard.\n\n## Expenses\n\nSubmit within 30 days.\n"
    response = await upload(client, account, "handbook.md", content * 10, "text/markdown")
    document = await wait_for_ready(client, response.json()["document"]["id"], account["headers"])
    assert document["status"] == "ready"
    assert document["doc_metadata"]["parser"] == "markdown"


async def test_identical_reupload_is_deduplicated(client, account):
    first = await upload(client, account, "same.txt", b"identical content here", "text/plain")
    second = await upload(client, account, "same.txt", b"identical content here", "text/plain")

    assert first.json()["deduplicated"] is False
    assert second.json()["deduplicated"] is True
    assert second.json()["document"]["id"] == first.json()["document"]["id"]


async def test_unsupported_file_type_is_rejected(client, account):
    response = await upload(
        client, account, "malware.exe", b"MZ\x90\x00", "application/octet-stream"
    )
    assert response.status_code == 415


async def test_content_that_contradicts_its_extension_is_rejected(client, account):
    """A zip renamed to .pdf must not reach the PDF parser."""
    response = await upload(
        client, account, "invoice.pdf", b"PK\x03\x04fake zip", "application/pdf"
    )
    assert response.status_code == 415


async def test_empty_upload_is_rejected(client, account):
    response = await upload(client, account, "empty.txt", b"", "text/plain")
    assert response.status_code == 422


async def test_oversized_upload_is_rejected(client, account, app):
    limit = app.state.settings.max_upload_bytes
    response = await upload(client, account, "huge.txt", b"x" * (limit + 1024), "text/plain")
    assert response.status_code == 413


async def test_documents_are_listed_with_cursor_pagination(client, account):
    for i in range(5):
        await upload(
            client, account, f"doc{i}.txt", f"content number {i}".encode() * 5, "text/plain"
        )

    first = await client.get(
        f"/workspaces/{account['workspace_id']}/documents?limit=2", headers=account["headers"]
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 2
    assert page["has_more"] is True

    second = await client.get(
        f"/workspaces/{account['workspace_id']}/documents?limit=2&cursor={page['next_cursor']}",
        headers=account["headers"],
    )
    # Pages must not overlap.
    first_ids = {d["id"] for d in page["items"]}
    second_ids = {d["id"] for d in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)


async def test_a_malformed_cursor_is_rejected(client, account):
    response = await client.get(
        f"/workspaces/{account['workspace_id']}/documents?cursor=garbage",
        headers=account["headers"],
    )
    assert response.status_code == 422


async def test_delete_removes_the_document(client, account):
    created = await upload(client, account, "temp.txt", b"delete me please", "text/plain")
    document_id = created.json()["document"]["id"]

    assert (
        await client.delete(f"/documents/{document_id}", headers=account["headers"])
    ).status_code == 200
    assert (
        await client.get(f"/documents/{document_id}", headers=account["headers"])
    ).status_code == 404


async def test_reprocess_reruns_ingestion_without_duplicating_chunks(client, account):
    created = await upload(
        client, account, "again.txt", b"reprocess this content " * 30, "text/plain"
    )
    document_id = created.json()["document"]["id"]
    first = await wait_for_ready(client, document_id, account["headers"])

    response = await client.post(f"/documents/{document_id}/reprocess", headers=account["headers"])
    assert response.status_code == 200

    second = await wait_for_ready(client, document_id, account["headers"])
    assert second["status"] == "ready"
    # Reprocessing must replace chunks, not append to them.
    assert second["chunk_count"] == first["chunk_count"]


async def test_workspace_stats_reflect_ingested_content(client, account):
    created = await upload(client, account, "stats.csv", CSV_CONTENT, "text/csv")
    await wait_for_ready(client, created.json()["document"]["id"], account["headers"])

    response = await client.get(
        f"/workspaces/{account['workspace_id']}/stats", headers=account["headers"]
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["document_count"] == 1
    assert stats["ready_document_count"] == 1
    assert stats["chunk_count"] > 0


async def test_a_scanned_pdf_is_recovered_by_reading_its_pages(client, account, fake_llm):
    """A scanned PDF has pages but no text layer. Without a fallback it ingests
    as empty and is invisible to retrieval — which reads to the user as the
    upload simply not working."""
    from tests.unit.test_rasterize import build_scanned_pdf

    fake_llm.responses = [
        "INVOICE 2026-0042. Total due: 1,250.00 EUR. Payable within 30 days.",
        "Terms and conditions continued on this page.",
    ]

    response = await upload(client, account, "scan.pdf", build_scanned_pdf(2), "application/pdf")
    assert response.status_code == 201

    document = await wait_for_ready(client, response.json()["document"]["id"], account["headers"])
    assert document["status"] == "ready", document.get("error_message")
    assert document["chunk_count"] > 0

    metadata = document["doc_metadata"]
    assert metadata["parser"] == "vision-ocr"
    assert metadata["ocr_fallback"] == "used"
    assert metadata["ocr_pages_read"] == 2
    assert metadata["ocr_pages_skipped"] == 0


async def test_a_recovered_scan_is_retrievable(client, account, fake_llm):
    """Recovery is only worth anything if the text becomes searchable."""
    from tests.unit.test_rasterize import build_scanned_pdf

    # Marker-dense on purpose: the offline hash embedder is lexical, not
    # semantic, so padding a short marker with unrelated filler drops cosine
    # similarity below the retrieval threshold for reasons that have nothing to
    # do with what is under test here.
    marker = "zylophone quarterly reconciliation 8817"
    fake_llm.responses = [(marker + " ") * 12]

    uploaded = await upload(client, account, "scan.pdf", build_scanned_pdf(1), "application/pdf")
    await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])

    conversation = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations", json={}, headers=account["headers"]
    )
    fake_llm.responses = ["Found it. [1]"]
    reply = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation.json()['id']}/messages",
        json={"content": marker},
        headers=account["headers"],
    )

    citations = reply.json()["assistant_message"]["citations"]
    assert citations, "the recovered scan should be retrievable"
    assert citations[0]["document_name"] == "scan.pdf"


async def test_a_truncated_scan_records_what_it_skipped(client, account, fake_llm, app):
    """Every page costs a vision call, so the read is bounded — and the
    omission has to be visible rather than silent."""
    from tests.unit.test_rasterize import build_scanned_pdf

    app.state.settings.ocr_max_pages = 2
    fake_llm.responses = ["Page one text.", "Page two text."]

    uploaded = await upload(
        client, account, "long-scan.pdf", build_scanned_pdf(6), "application/pdf"
    )
    document = await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])

    assert document["status"] == "ready", document.get("error_message")
    assert document["doc_metadata"]["ocr_pages_read"] == 2
    assert document["doc_metadata"]["ocr_pages_skipped"] == 4
    app.state.settings.ocr_max_pages = 20


async def test_a_scan_that_yields_no_text_fails_with_a_reason(client, account, fake_llm):
    """Better a document marked failed with an explanation than one that
    silently ingests as empty."""
    from tests.unit.test_rasterize import build_scanned_pdf

    fake_llm.responses = ["", ""]
    uploaded = await upload(
        client, account, "blank-scan.pdf", build_scanned_pdf(2), "application/pdf"
    )
    document = await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])

    assert document["status"] == "failed"
    assert "scanned" in document["error_message"].lower()


async def test_chunks_record_the_embedding_space_that_produced_them(
    client, account, app, session_factory
):
    """A chunk is only comparable to a query embedded the same way.

    Vectors from different providers are not commensurable, and cosine distance
    between them returns a plausible number rather than an error, so nothing
    downstream can notice the mismatch on its own. Retrieval therefore filters
    on the recorded space, and this test pins both halves: the stamp is written,
    and a query from a different space matches nothing rather than ranking
    against vectors it cannot be compared to.
    """
    from sqlalchemy import select

    from app.models.documents import DocumentChunk
    from app.repositories.documents import ChunkRepository

    created = await upload(
        client,
        account,
        "spaces.txt",
        b"Expense approvals above five thousand dollars require the finance lead." * 20,
        "text/plain",
    )
    document = await wait_for_ready(client, created.json()["document"]["id"], account["headers"])
    assert document["chunk_count"] > 0

    embeddings = app.state.embeddings
    workspace_id = uuid.UUID(account["workspace_id"])

    async with session_factory() as session:
        stored = (
            (
                await session.execute(
                    select(DocumentChunk.embedding_model).where(
                        DocumentChunk.document_id == uuid.UUID(document["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert stored, "the document produced no chunks"
        assert set(stored) == {embeddings.signature}

        repo = ChunkRepository(session)
        query_vector = await embeddings.embed_one("expense approval limit", kind="query")

        same_space = await repo.search(
            workspace_id=workspace_id,
            embedding=query_vector,
            embedding_model=embeddings.signature,
        )
        assert same_space, "the chunk should be found in its own embedding space"

        other_space = await repo.search(
            workspace_id=workspace_id,
            embedding=query_vector,
            embedding_model="openai:text-embedding-3-small:1024",
        )
        assert other_space == [], "chunks from another embedding space must not be returned"


async def test_a_file_remembers_the_conversation_it_arrived_in(client, account):
    """The rail shows three stores — what the assistant made, what you dropped
    into this thread, and what the workspace holds — and they can only be told
    apart if a file records how it arrived."""
    conversation = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": "with a file"},
        headers=account["headers"],
    )
    conversation_id = conversation.json()["id"]

    in_thread = await client.post(
        f"/workspaces/{account['workspace_id']}/documents",
        files={"file": ("dropped.txt", io.BytesIO(b"in the thread"), "text/plain")},
        data={"conversation_id": conversation_id},
        headers=account["headers"],
    )
    assert in_thread.status_code == 201, in_thread.text
    assert in_thread.json()["document"]["conversation_id"] == conversation_id


async def test_a_file_uploaded_outside_a_thread_belongs_to_the_workspace(client, account):
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/documents",
        files={"file": ("shared.txt", io.BytesIO(b"workspace wide"), "text/plain")},
        headers=account["headers"],
    )
    assert response.status_code == 201
    assert response.json()["document"]["conversation_id"] is None


async def test_where_a_file_arrived_does_not_narrow_retrieval(client, account):
    """A document dropped into one thread is still the workspace's knowledge.
    Scoping search to the thread would quietly hide it from every other one."""
    conversation = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": "origin"},
        headers=account["headers"],
    )
    uploaded = await client.post(
        f"/workspaces/{account['workspace_id']}/documents",
        files={
            "file": (
                "badger.txt",
                io.BytesIO(b"The quarterly badger census counted 41 badgers." * 8),
                "text/plain",
            )
        },
        data={"conversation_id": conversation.json()["id"]},
        headers=account["headers"],
    )
    document = await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])
    assert document["status"] == "ready"

    # Asked from a different conversation entirely.
    elsewhere = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": "somewhere else"},
        headers=account["headers"],
    )
    answer = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{elsewhere.json()['id']}/messages",
        json={"content": "How many badgers were counted?"},
        headers=account["headers"],
    )
    assert answer.status_code == 201
    assert answer.json()["assistant_message"][
        "citations"
    ], "a file uploaded in another thread must still be retrievable"
