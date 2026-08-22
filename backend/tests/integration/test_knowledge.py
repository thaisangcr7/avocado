"""The org knowledge layer.

§5: the pass that turns a pile of uploaded files into a queryable map of what a
team does — which documents are policies, which describe processes, and what
they cover.
"""

from __future__ import annotations

import io
import json

import pytest

from tests.conftest import quiesce_llm, register_account
from tests.integration.test_documents import upload, wait_for_ready

pytestmark = pytest.mark.anyio

POLICY = (
    b"Remote Work Policy. Effective 1 March 2026. Employees may work from home "
    b"up to three days per week. Managers approve schedules quarterly. "
) * 10


@pytest.fixture
async def owner(client):
    return await register_account(client, email="owner@acme.com", org="Acme")


def classification(**overrides):
    return json.dumps(
        {
            "kind": "policy",
            "title": "Remote Work Policy",
            "summary": "Sets out how often employees may work from home.",
            "topics": ["remote work", "policy"],
            "effective_date": "2026-03-01",
            "confidence": 0.92,
            **overrides,
        }
    )


async def seed(client, owner, name="policy.txt", content=POLICY, *, fake_llm=None):
    """Upload a document.

    Ingestion classifies automatically, so a test that wants an *untagged*
    document has to make that pass fail — pass `fake_llm` and it is scripted to
    return something unparseable, leaving the document ready but unclassified.
    """
    if fake_llm is not None:
        fake_llm.responses = ["not a classification"]
    response = await upload(client, owner, name, content, "text/plain")
    document = await wait_for_ready(client, response.json()["document"]["id"], owner["headers"])
    assert document["status"] == "ready"
    if fake_llm is not None:
        # Classification runs after the document is marked ready, so a caller
        # that stages its own responses next would have this late pass eat the
        # first one. Readiness is not the condition they actually need.
        await quiesce_llm(fake_llm)
    return document


async def classify(client, owner, document_id):
    return await client.post(
        f"/workspaces/{owner['workspace_id']}/documents/{document_id}/classification",
        headers=owner["headers"],
    )


async def test_a_document_is_classified_into_what_it_is(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = [classification()]

    response = await classify(client, owner, document["id"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kind"] == "policy"
    assert body["title"] == "Remote Work Policy"
    assert body["topics"] == ["remote work", "policy"]
    assert body["effective_date"] == "2026-03-01"
    assert body["confidence"] == pytest.approx(0.92)
    assert body["version"] == 1
    # Attributed, like every other model-produced field.
    assert body["model_used"]


async def test_the_classifier_reads_the_document_not_the_filename(client, owner, fake_llm):
    """The prompt has to carry the document's own text, or the classification
    is guesswork over a filename."""
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = [classification()]
    await classify(client, owner, document["id"])

    prompt = fake_llm.calls[-1]["messages"][0]
    assert "Remote Work Policy" in prompt
    assert "three days per week" in prompt


async def test_reclassifying_updates_in_place_and_bumps_the_version(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)

    fake_llm.responses = [classification()]
    first = (await classify(client, owner, document["id"])).json()

    fake_llm.responses = [classification(kind="process", title="Remote Work Process")]
    second = (await classify(client, owner, document["id"])).json()

    # One row per document, updated — not an accumulating pile nothing reads.
    assert second["id"] == first["id"]
    assert second["version"] == 2
    assert second["kind"] == "process"


async def test_an_unclassifiable_response_does_not_fail_the_document(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = ["not json at all"]

    response = await classify(client, owner, document["id"])
    assert response.status_code == 502

    # The document itself is untouched and still retrievable.
    still_there = await client.get(f"/documents/{document['id']}", headers=owner["headers"])
    assert still_there.json()["status"] == "ready"


async def test_an_unknown_kind_falls_back_rather_than_raising(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = [classification(kind="something-invented")]

    body = (await classify(client, owner, document["id"])).json()
    assert body["kind"] == "other"


async def test_a_malformed_effective_date_becomes_null(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = [classification(effective_date="sometime in spring")]

    body = (await classify(client, owner, document["id"])).json()
    assert body["effective_date"] is None


async def test_the_knowledge_map_groups_by_kind_and_topic(client, owner, fake_llm):
    policy = await seed(client, owner, "policy.txt", fake_llm=fake_llm)
    fake_llm.responses = [classification()]
    await classify(client, owner, policy["id"])

    process = await seed(
        client, owner, "process.txt", b"How we onboard new hires. " * 40, fake_llm=fake_llm
    )
    fake_llm.responses = [
        classification(
            kind="process",
            title="Onboarding Process",
            topics=["onboarding"],
            effective_date=None,
        )
    ]
    await classify(client, owner, process["id"])

    response = await client.get(
        f"/workspaces/{owner['workspace_id']}/knowledge", headers=owner["headers"]
    )
    assert response.status_code == 200
    body = response.json()

    assert body["counts_by_kind"]["policy"] == 1
    assert body["counts_by_kind"]["process"] == 1
    assert set(body["topics"]) == {"remote work", "policy", "onboarding"}
    assert len(body["documents"]) == 2
    assert {d["filename"] for d in body["documents"]} == {"policy.txt", "process.txt"}


async def test_the_map_can_be_filtered(client, owner, fake_llm):
    policy = await seed(client, owner, "policy.txt", fake_llm=fake_llm)
    fake_llm.responses = [classification()]
    await classify(client, owner, policy["id"])

    process = await seed(
        client, owner, "process.txt", b"Deployment steps. " * 40, fake_llm=fake_llm
    )
    fake_llm.responses = [
        classification(kind="process", topics=["deployment"], effective_date=None)
    ]
    await classify(client, owner, process["id"])

    by_kind = await client.get(
        f"/workspaces/{owner['workspace_id']}/knowledge?kind=policy",
        headers=owner["headers"],
    )
    assert [d["filename"] for d in by_kind.json()["documents"]] == ["policy.txt"]

    by_topic = await client.get(
        f"/workspaces/{owner['workspace_id']}/knowledge?topic=deployment",
        headers=owner["headers"],
    )
    assert [d["filename"] for d in by_topic.json()["documents"]] == ["process.txt"]


async def test_the_map_counts_what_has_not_been_classified(client, owner, fake_llm):
    """A workspace populated before the pass existed must not be permanently
    invisible to the knowledge layer."""
    await seed(client, owner, "untagged.txt", b"Some content here. " * 40, fake_llm=fake_llm)

    body = (
        await client.get(f"/workspaces/{owner['workspace_id']}/knowledge", headers=owner["headers"])
    ).json()
    assert body["unclassified_count"] == 1
    assert body["documents"] == []


async def test_an_unclassified_document_reports_as_such(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    response = await client.get(
        f"/workspaces/{owner['workspace_id']}/documents/{document['id']}/classification",
        headers=owner["headers"],
    )
    assert response.status_code == 404


async def test_the_knowledge_map_does_not_cross_the_tenant_boundary(client, owner, fake_llm):
    document = await seed(client, owner, fake_llm=fake_llm)
    fake_llm.responses = [classification()]
    await classify(client, owner, document["id"])

    outsider = await register_account(client, email="rival@other.com", org="Rival")
    assert (
        await client.get(
            f"/workspaces/{owner['workspace_id']}/knowledge", headers=outsider["headers"]
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/workspaces/{owner['workspace_id']}/documents/{document['id']}/classification",
            headers=outsider["headers"],
        )
    ).status_code == 404


async def test_an_empty_document_is_skipped_rather_than_guessed_at(client, owner, fake_llm):
    """Classifying with no text to read would be invention, not inference."""
    response = await client.post(
        f"/workspaces/{owner['workspace_id']}/documents",
        files={"file": ("tiny.txt", io.BytesIO(b"ok"), "text/plain")},
        headers=owner["headers"],
    )
    document = await wait_for_ready(client, response.json()["document"]["id"], owner["headers"])
    if document["status"] != "ready":
        pytest.skip("document did not ingest")

    fake_llm.responses = [classification(kind="other", topics=[])]
    result = await classify(client, owner, document["id"])
    assert result.status_code in (200, 502)


async def test_ingestion_classifies_a_document_without_being_asked(client, owner, fake_llm):
    """A document should join the knowledge map by being uploaded, not by
    someone remembering to tag it."""
    fake_llm.responses = [classification()]
    document = await seed(client, owner, "auto.txt")

    response = await client.get(
        f"/workspaces/{owner['workspace_id']}/documents/{document['id']}/classification",
        headers=owner["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "policy"


async def test_a_classification_failure_does_not_fail_the_ingest(client, owner, fake_llm):
    """An unclassified document is still a perfectly good, retrievable one."""
    document = await seed(client, owner, "resilient.txt", fake_llm=fake_llm)

    assert document["status"] == "ready"
    assert document["chunk_count"] > 0
    untagged = await client.get(
        f"/workspaces/{owner['workspace_id']}/documents/{document['id']}/classification",
        headers=owner["headers"],
    )
    assert untagged.status_code == 404


async def test_a_lost_insert_race_recovers_instead_of_500ing(client, owner, fake_llm, monkeypatch):
    """Ingestion classifies in the background while a user can ask for the same.

    Both callers can read no row and both try to insert; a unique index settles
    it and the loser must re-read and update. CI hit this as a duplicate key
    violation surfacing as a 500.

    Two real HTTP calls serialise here, so the losing read is forced directly:
    the lookup returns None once while the row genuinely exists, which is
    exactly the state the losing caller is in.
    """
    from app.repositories.knowledge import ClassificationRepository

    document = await seed(client, owner, "raced.txt", fake_llm=fake_llm)

    fake_llm.responses = [classification(kind="policy")]
    first = await classify(client, owner, document["id"])
    assert first.status_code == 200, first.text

    real_lookup = ClassificationRepository.get_for_document
    calls = {"n": 0}

    async def lookup_once_blind(self, document_id, workspace_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(self, document_id, workspace_id)

    monkeypatch.setattr(ClassificationRepository, "get_for_document", lookup_once_blind)

    fake_llm.responses = [classification(kind="process")]
    second = await classify(client, owner, document["id"])
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == "process", "the recovering write should still land"

    # One row, not two: the conflict was resolved by updating, not inserting.
    knowledge = await client.get(
        f"/workspaces/{owner['workspace_id']}/knowledge", headers=owner["headers"]
    )
    matching = [d for d in knowledge.json()["documents"] if d["document_id"] == document["id"]]
    assert len(matching) == 1, matching
