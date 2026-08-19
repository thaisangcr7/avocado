"""The analysis engine: a natural-language question becomes executed code.

    question + table schema  ->  generated pandas  ->  static screen
                             ->  sandboxed execution  ->  result + summary

Three properties this is built around:

* **It computes.** The model never sees the data — only the schema. It writes a
  program; the program produces the number. That is what makes an answer
  reproducible and auditable rather than plausible.
* **It fails closed.** If no compliant sandbox is available, the run is
  refused. There is no path where generated code executes with weaker isolation
  than §13 requires.
* **It retries on its own errors.** A `KeyError` on a column name is the common
  failure and is entirely recoverable: the traceback goes back to the model
  with the schema, once. Two attempts, then it stops — a third rarely succeeds
  and costs real money.
"""

from __future__ import annotations

import base64
import json
import uuid

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.clients.sandbox.base import Sandbox, SandboxDataset, SandboxLimits, SandboxResult
from app.clients.sandbox.guard import screen_code
from app.clients.storage.base import StorageClient, build_storage_key
from app.core.errors import NotFoundError, SandboxUnavailableError, ValidationError
from app.core.logging import get_logger
from app.models.analysis import AnalysisRun
from app.models.documents import DocumentTable
from app.models.enums import AnalysisStatus
from app.repositories.analysis import AnalysisRunRepository
from app.repositories.documents import DocumentRepository, DocumentTableRepository
from app.schemas.analysis import AnalysisRunResponse
from app.services.usage_service import UsageService

log = get_logger(__name__)

MAX_ATTEMPTS = 2

CODE_SYSTEM_PROMPT = """You write pandas code to answer questions about a dataset.

The DataFrame is already loaded and bound to the variable named in the schema. \
Do not read any file, and do not create sample data.

Available: `pd` (pandas), `np` (numpy), `plt` (matplotlib.pyplot). Nothing else \
may be imported.

Requirements:
- Assign the answer to a variable named `result`. Use a DataFrame or Series for \
tabular answers, a plain number or string for a single value.
- Use `print()` for anything that helps explain the result.
- Only draw a chart with `plt` when the question asks for a trend, comparison, \
or distribution. Do not call `plt.show()`.
- Use exactly the column names given in the schema — they are case-sensitive.
- Handle missing values explicitly rather than letting them propagate silently.

Return the code and a one-sentence explanation of the approach."""

CODE_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "The pandas code to execute."},
        "explanation": {
            "type": "string",
            "description": "One sentence on the approach taken.",
        },
    },
    "required": ["code", "explanation"],
    "additionalProperties": False,
}

SUMMARY_PROMPT = """State the answer to the question from these computed results.

Be direct and lead with the answer. Quote the actual figures. Two or three \
sentences at most. Do not describe the code or the process."""


class AnalysisService:
    def __init__(
        self,
        *,
        runs: AnalysisRunRepository,
        documents: DocumentRepository,
        tables: DocumentTableRepository,
        storage: StorageClient,
        sandbox: Sandbox | None,
        limits: SandboxLimits,
        router: ModelRouter,
        usage: UsageService,
    ) -> None:
        self._runs = runs
        self._documents = documents
        self._tables = tables
        self._storage = storage
        self._sandbox = sandbox
        self._limits = limits
        self._router = router
        self._usage = usage

    async def run(
        self,
        *,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        question: str,
        table_id: uuid.UUID | None,
        preferred_model: str | None,
    ) -> AnalysisRunResponse:
        if self._sandbox is None:
            raise SandboxUnavailableError(
                "Analysis is disabled because no execution sandbox is configured."
            )
        if not await self._sandbox.available():
            # Fail closed. Running generated code outside the sandbox to keep
            # the feature working would trade the one guarantee that makes it
            # safe for a nicer error page.
            raise SandboxUnavailableError(
                "The analysis sandbox is unavailable, so this question cannot be "
                "computed right now. Analysis never runs outside the sandbox."
            )

        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise NotFoundError("Document not found.")

        table = await self._resolve_table(document_id, workspace_id, table_id)
        csv_bytes = await self._storage.get(table.storage_key)

        run = await self._runs.add(
            AnalysisRun(
                workspace_id=workspace_id,
                document_id=document_id,
                user_id=user_id,
                question=question,
                status=AnalysisStatus.GENERATING,
            )
        )
        await self._runs.commit()

        variable = _variable_name(table.name)
        schema = _schema_description(table, variable)
        provider, spec = self._router.resolve(
            task=TaskType.CODE_GENERATION, preferred_model=preferred_model
        )

        error_feedback: str | None = None
        result: SandboxResult | None = None
        code = ""
        explanation = ""
        total_in = total_out = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            run.attempt_count = attempt

            prompt = _build_prompt(question, schema, error_feedback, code)
            generation = await provider.generate(
                messages=[ChatMessage(role="user", content=prompt)],
                model=spec.id,
                system=CODE_SYSTEM_PROMPT,
                max_tokens=4096,
                json_schema=CODE_SCHEMA,
            )
            total_in += generation.usage.input_tokens
            total_out += generation.usage.output_tokens

            try:
                payload = json.loads(generation.text)
                code = payload["code"]
                explanation = payload.get("explanation", "")
            except (json.JSONDecodeError, KeyError, TypeError):
                error_feedback = "The previous response was not valid JSON."
                continue

            screen = screen_code(code)
            if not screen.allowed:
                # The container is the real boundary; this is the early, clear
                # rejection. Feed the reason back so the retry avoids it.
                log.warning("analysis_code_rejected", reason=screen.reason)
                error_feedback = f"That code was rejected: {screen.reason}"
                continue

            run.status = AnalysisStatus.EXECUTING
            run.generated_code = code
            run.code_explanation = explanation
            await self._runs.commit()

            result = await self._sandbox.run(
                code=code,
                datasets=[
                    SandboxDataset(variable=variable, filename="data.csv", content=csv_bytes)
                ],
                limits=self._limits,
            )

            if result.success:
                break

            # A timeout or an OOM will not be fixed by rewriting the query the
            # same way; only genuine code errors are worth another attempt.
            if result.timed_out or attempt == MAX_ATTEMPTS:
                break
            error_feedback = (result.error or "The code failed.")[:2000]
            log.info("analysis_retrying", run_id=str(run.id), attempt=attempt)

        return await self._finalise(
            run=run,
            result=result,
            code=code,
            explanation=explanation,
            question=question,
            provider_model=spec.id,
            workspace_id=workspace_id,
            org_id=org_id,
            user_id=user_id,
            tokens=(total_in, total_out),
            preferred_model=preferred_model,
        )

    async def _finalise(
        self,
        *,
        run: AnalysisRun,
        result: SandboxResult | None,
        code: str,
        explanation: str,
        question: str,
        provider_model: str,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        tokens: tuple[int, int],
        preferred_model: str | None,
    ) -> AnalysisRunResponse:
        run.model_used = provider_model
        run.generated_code = code or run.generated_code
        run.code_explanation = explanation or run.code_explanation

        if result is None or not result.success:
            run.status = AnalysisStatus.FAILED
            run.error_message = (
                result.error if result and result.error else "Analysis could not be completed."
            )[:4000]
            run.execution_ms = result.execution_ms if result else None
        else:
            run.status = AnalysisStatus.SUCCEEDED
            run.execution_ms = result.execution_ms
            run.result_data = {
                "stdout": result.stdout,
                "tables": result.tables,
                "scalars": result.scalars,
            }
            if result.chart_png_b64:
                run.chart_url = await self._store_chart(workspace_id, run.id, result.chart_png_b64)
            run.result_summary = await self._summarise(question, result, preferred_model, tokens)

        await self._runs.commit()
        await self._usage.record(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            endpoint="documents.analyze",
            model=provider_model,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            latency_ms=run.execution_ms or 0,
            success=run.status is AnalysisStatus.SUCCEEDED,
        )
        log.info(
            "analysis_completed",
            run_id=str(run.id),
            status=run.status.value,
            attempts=run.attempt_count,
        )
        return AnalysisRunResponse.model_validate(run)

    async def _summarise(
        self,
        question: str,
        result: SandboxResult,
        preferred_model: str | None,
        tokens: tuple[int, int],
    ) -> str:
        """Turn computed output into a sentence a person can read.

        Falls back to the raw stdout if the model call fails — a correct
        computation should not be lost because the prose step broke.
        """
        evidence = {
            "stdout": result.stdout[:4000],
            "tables": result.tables[:1],
            "scalars": result.scalars,
        }
        try:
            provider, spec = self._router.resolve(
                task=TaskType.SUMMARIZATION, preferred_model=preferred_model
            )
            summary = await provider.generate(
                messages=[
                    ChatMessage(
                        role="user",
                        content=(
                            f"Question: {question}\n\n"
                            f"Computed results:\n{json.dumps(evidence, default=str)[:8000]}"
                        ),
                    )
                ],
                model=spec.id,
                system=SUMMARY_PROMPT,
                max_tokens=512,
            )
            if summary.text.strip():
                return summary.text.strip()
        except Exception:
            log.debug("analysis_summary_failed", exc_info=True)

        return result.stdout.strip()[:1000] or "The analysis completed."

    async def _store_chart(self, workspace_id: uuid.UUID, run_id: uuid.UUID, chart_b64: str) -> str:
        key = build_storage_key(workspace_id, "charts", str(run_id), "chart.png")
        await self._storage.put(key, base64.b64decode(chart_b64), content_type="image/png")
        return key

    async def _resolve_table(
        self,
        document_id: uuid.UUID,
        workspace_id: uuid.UUID,
        table_id: uuid.UUID | None,
    ) -> DocumentTable:
        tables = await self._tables.list_for_document(document_id, workspace_id)
        if not tables:
            raise ValidationError(
                "This document has no analysable table. Analysis works on "
                "spreadsheets and CSV files."
            )
        if table_id is None:
            return tables[0]

        match = next((t for t in tables if t.id == table_id), None)
        if match is None:
            raise NotFoundError("Table not found in this document.")
        return match

    async def get(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> AnalysisRunResponse:
        run = await self._runs.get_scoped(run_id, workspace_id)
        if run is None:
            raise NotFoundError("Analysis run not found.")
        return AnalysisRunResponse.model_validate(run)

    async def list_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[AnalysisRunResponse]:
        runs = await self._runs.list_for_document(document_id, workspace_id)
        return [AnalysisRunResponse.model_validate(r) for r in runs]


def _variable_name(table_name: str) -> str:
    """A safe Python identifier for the DataFrame the code will reference."""
    cleaned = "".join(c if c.isalnum() else "_" for c in table_name.lower()).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"df_{cleaned}"
    return cleaned[:40] or "df"


def _schema_description(table: DocumentTable, variable: str) -> str:
    """The schema the model writes code against — never the data itself."""
    lines = [
        f"DataFrame variable: {variable}",
        f"Source: {table.name} ({table.row_count} rows, {table.column_count} columns)",
        "",
        "Columns:",
    ]
    for column in table.columns:
        samples = column.get("sample_values") or []
        sample_text = ", ".join(str(s) for s in samples[:3])
        nulls = column.get("null_count", 0)
        lines.append(
            f"  - {column['name']} ({column.get('dtype', 'unknown')})"
            + (f" — e.g. {sample_text}" if sample_text else "")
            + (f" — {nulls} missing" if nulls else "")
        )
    return "\n".join(lines)


def _build_prompt(
    question: str, schema: str, error_feedback: str | None, previous_code: str
) -> str:
    prompt = f"{schema}\n\nQuestion: {question}"
    if error_feedback:
        prompt += (
            f"\n\nYour previous attempt failed.\n\nPrevious code:\n{previous_code}\n\n"
            f"Error:\n{error_feedback}\n\nFix it and return corrected code."
        )
    return prompt
