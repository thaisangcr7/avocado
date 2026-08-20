"""The analysis engine: code generation, execution, retry and failure modes.

These use a scripted sandbox so the service's own logic is what is under test.
Real container isolation is verified separately in `test_sandbox_security.py`.
"""

from __future__ import annotations

import json

import pytest

from app.clients.sandbox.base import SandboxResult
from tests.integration.test_documents import CSV_CONTENT, upload, wait_for_ready

pytestmark = pytest.mark.anyio


def codegen_calls(fake_llm):
    """Only the analysis code-generation calls.

    Ingestion also classifies a document, so positional indexing into every
    recorded call would silently point at the wrong one.
    """
    return [
        call
        for call in fake_llm.calls
        if (call.get("json_schema") or {}).get("properties", {}).keys() >= {"code"}
    ]


async def seed_spreadsheet(client, account):
    response = await upload(client, account, "sales.csv", CSV_CONTENT, "text/csv")
    assert response.status_code == 201
    document = await wait_for_ready(client, response.json()["document"]["id"], account["headers"])
    assert document["status"] == "ready", document.get("error_message")
    return document


async def test_a_question_is_answered_by_generated_and_executed_code(
    client, account, fake_llm, fake_sandbox
):
    document = await seed_spreadsheet(client, account)
    fake_llm.responses = [
        json.dumps(
            {
                "code": "result = sales.groupby('region')['revenue'].sum().reset_index()",
                "explanation": "Group by region and sum revenue.",
            }
        ),
        "North totals 25,000 and South totals 20,000.",
    ]

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is total revenue by region?"},
        headers=account["headers"],
    )
    assert response.status_code == 201
    run = response.json()

    assert run["status"] == "succeeded"
    # The program is part of the answer — that is what makes it checkable.
    assert "groupby" in run["generated_code"]
    assert run["code_explanation"]
    assert run["result_summary"]
    assert run["result_data"]["tables"][0]["columns"] == ["region", "revenue"]
    assert run["attempt_count"] == 1
    assert fake_sandbox.executed_code


async def test_code_that_fails_is_retried_with_the_error(client, account, fake_llm, fake_sandbox):
    """A wrong column name is the common failure and is recoverable."""
    document = await seed_spreadsheet(client, account)

    fake_sandbox.results = [
        SandboxResult(success=False, error="KeyError: 'sales_total'", execution_ms=10),
        SandboxResult(success=True, stdout="45000", scalars={"result": 45000}, execution_ms=12),
    ]
    fake_llm.responses = [
        json.dumps({"code": "result = sales['sales_total'].sum()", "explanation": "First try."}),
        json.dumps({"code": "result = sales['revenue'].sum()", "explanation": "Corrected column."}),
        "Total revenue is 45,000.",
    ]

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is total revenue?"},
        headers=account["headers"],
    )
    run = response.json()

    assert run["status"] == "succeeded"
    assert run["attempt_count"] == 2
    # The retry prompt must actually carry the failure back to the model.
    retry_prompt = codegen_calls(fake_llm)[1]["messages"][0]
    assert "KeyError" in retry_prompt
    assert "sales_total" in retry_prompt


async def test_retries_are_bounded(client, account, fake_llm, fake_sandbox):
    document = await seed_spreadsheet(client, account)

    fake_sandbox.results = [
        SandboxResult(success=False, error="KeyError: 'a'", execution_ms=5),
        SandboxResult(success=False, error="KeyError: 'b'", execution_ms=5),
        SandboxResult(success=False, error="KeyError: 'c'", execution_ms=5),
    ]
    fake_llm.responses = [
        json.dumps({"code": f"result = sales['{c}'].sum()", "explanation": "x"}) for c in "abc"
    ]

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "unanswerable question"},
        headers=account["headers"],
    )
    run = response.json()

    assert run["status"] == "failed"
    assert run["attempt_count"] == 2  # not 3 — a third attempt rarely helps
    assert run["error_message"]


async def test_a_timeout_is_not_retried(client, account, fake_llm, fake_sandbox):
    """Rewriting the same query will not make it finish faster."""
    document = await seed_spreadsheet(client, account)

    fake_sandbox.results = [
        SandboxResult(
            success=False,
            timed_out=True,
            error="Analysis exceeded the 30s time limit.",
            execution_ms=30_000,
        )
    ]
    fake_llm.responses = [json.dumps({"code": "while True: pass", "explanation": "x"})]

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "something very slow"},
        headers=account["headers"],
    )
    run = response.json()

    assert run["status"] == "failed"
    assert run["attempt_count"] == 1
    assert "time limit" in run["error_message"]


async def test_dangerous_generated_code_never_reaches_the_sandbox(
    client, account, fake_llm, fake_sandbox
):
    document = await seed_spreadsheet(client, account)

    fake_llm.responses = [
        json.dumps({"code": "import socket\nresult = socket.gethostname()", "explanation": "x"}),
        json.dumps({"code": "result = sales['revenue'].sum()", "explanation": "Corrected."}),
        "Total revenue is 45,000.",
    ]

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "what host is this"},
        headers=account["headers"],
    )
    assert response.status_code == 201

    # The screened attempt is never executed; only the safe retry is.
    assert all("socket" not in code for code in fake_sandbox.executed_code)
    # And the rejection reason is fed back so the retry can avoid it.
    assert "not permitted" in codegen_calls(fake_llm)[1]["messages"][0]


async def test_analysis_fails_closed_when_no_sandbox_is_available(client, account, fake_sandbox):
    """The guarantee that matters most: no sandbox means no execution."""
    document = await seed_spreadsheet(client, account)
    fake_sandbox.up = False

    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is total revenue?"},
        headers=account["headers"],
    )
    assert response.status_code == 503
    assert "sandbox" in response.json()["detail"].lower()
    assert fake_sandbox.executed_code == []


async def test_a_document_with_no_table_cannot_be_analysed(client, account):
    response = await upload(
        client, account, "notes.txt", b"Just prose, no table here at all. " * 20, "text/plain"
    )
    document = await wait_for_ready(client, response.json()["document"]["id"], account["headers"])

    analysed = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is the total?"},
        headers=account["headers"],
    )
    assert analysed.status_code == 422
    assert "spreadsheet" in analysed.json()["detail"].lower()


async def test_a_run_can_be_fetched_and_listed(client, account, fake_llm):
    document = await seed_spreadsheet(client, account)
    fake_llm.responses = [
        json.dumps({"code": "result = sales['revenue'].sum()", "explanation": "Sum."}),
        "Total is 45,000.",
    ]

    created = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is total revenue?"},
        headers=account["headers"],
    )
    run_id = created.json()["id"]

    fetched = await client.get(f"/analysis-runs/{run_id}", headers=account["headers"])
    assert fetched.status_code == 200
    assert fetched.json()["id"] == run_id

    listed = await client.get(
        f"/documents/{document['id']}/analysis-runs", headers=account["headers"]
    )
    assert [r["id"] for r in listed.json()] == [run_id]


async def test_a_generated_chart_is_stored_and_served(client, account, fake_llm, fake_sandbox):
    import base64

    document = await seed_spreadsheet(client, account)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"fake image bytes").decode()
    fake_sandbox.results = [
        SandboxResult(success=True, stdout="charted", chart_png_b64=png, execution_ms=20)
    ]
    fake_llm.responses = [
        json.dumps({"code": "sales.plot()\nresult = sales", "explanation": "Plot."}),
        "Here is the trend.",
    ]

    created = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "Show the revenue trend"},
        headers=account["headers"],
    )
    run = created.json()
    assert run["chart_url"]

    chart = await client.get(f"/analysis-runs/{run['id']}/chart", headers=account["headers"])
    assert chart.status_code == 200
    assert chart.headers["content-type"] == "image/png"
    assert chart.content.startswith(b"\x89PNG")


async def test_the_model_receives_the_schema_but_never_the_data(client, account, fake_llm):
    """Code is written against column names and types, not against rows."""
    document = await seed_spreadsheet(client, account)
    fake_llm.responses = [
        json.dumps({"code": "result = sales['revenue'].sum()", "explanation": "Sum."}),
        "Total is 45,000.",
    ]

    await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "What is total revenue?"},
        headers=account["headers"],
    )

    prompt = codegen_calls(fake_llm)[0]["messages"][0]
    assert "revenue" in prompt and "region" in prompt  # schema is present
    # The bulk of the rows are not in the prompt.
    assert "12000" not in prompt


async def test_a_question_that_is_too_short_is_rejected(client, account):
    document = await seed_spreadsheet(client, account)
    response = await client.post(
        f"/documents/{document['id']}/analyze",
        json={"question": "x"},
        headers=account["headers"],
    )
    assert response.status_code == 422
