"""The workspace report engine: every spreadsheet becomes one executive briefing.

    all workspace tables  ->  deterministic profiling in the sandbox
                          ->  computed KPIs + aggregated series (real numbers)
                          ->  one generation binds narrative + charts to them

Two properties this shares with the single-table analysis engine:

* **It computes.** The model never authors a data row. The profiler produces
  every number; the model only writes the narrative and chooses which computed
  series each chart plots. A chart whose fields do not match a computed series
  is dropped before it can reach the browser.
* **It fails closed.** Profiling runs in the same isolated sandbox as model
  code. With no compliant sandbox, the report is refused rather than computed
  on the host.
"""

from __future__ import annotations

import json
import re
import uuid

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.clients.sandbox.base import Sandbox, SandboxDataset, SandboxLimits
from app.clients.storage.base import StorageClient
from app.core.errors import SandboxUnavailableError, ValidationError
from app.core.logging import get_logger
from app.repositories.documents import DocumentTableRepository
from app.schemas.analysis import (
    ExecutiveReport,
    ReportKpi,
    ReportPlan,
    ReportSection,
    ReportSeries,
)
from app.services.rag_service import ANSWER_VOICE
from app.services.report_profiler import build_profiler_code
from app.services.usage_service import UsageService

log = get_logger(__name__)

# A report reads across the workspace, but every mounted CSV is memory the
# sandbox has to hold at once. Six of the largest tables is plenty of signal
# for an executive read without risking the container's memory cap.
MAX_DATASETS = 6

REPORT_PROMPT = (
    """You are Avocado, writing a whole-workspace executive briefing \
for a team's leaders.

You are given COMPUTED evidence: for each dataset, its real KPIs and small aggregated \
series (already calculated from the full data). These numbers are the only truth.

Rules:
- Never invent a number, dataset, column, or category. Use only values present in the evidence.
- Lead with a single thesis: the one thing leadership should act on this cycle.
- Choose 3-6 headline KPIs for the top strip. For each, set source_key to the exact key of \
a computed KPI in the evidence, and choose a format (currency, compact_currency, percent, \
number, or compact_number). The service fills the figure from that computed value — never \
write the number yourself. Set tone to positive, negative, warning, or neutral to match \
performance.
- Write one section per meaningful theme (revenue, delivery, support, hiring, finance, etc.). \
Give each a status of on_course, watch, or off_course, and 2-4 sentences of narrative that \
name specific computed figures.
- For each chart, set series_key to the exact key of a computed series, and set x/y (and \
optional color) fields to exact column names of that series. Prefer line/area for series \
over time, bar for category comparisons. At most 3 charts per section.
- State honest limitations only when the evidence is genuinely thin.
- Do not discuss code, methodology, tokens, or the analysis process."""
    + ANSWER_VOICE
)


class ReportService:
    def __init__(
        self,
        *,
        tables: DocumentTableRepository,
        storage: StorageClient,
        sandbox: Sandbox | None,
        limits: SandboxLimits,
        router: ModelRouter,
        usage: UsageService,
    ) -> None:
        self._tables = tables
        self._storage = storage
        self._sandbox = sandbox
        self._limits = limits
        self._router = router
        self._usage = usage

    async def generate(
        self,
        *,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        focus: str | None,
        preferred_model: str | None,
    ) -> ExecutiveReport:
        if self._sandbox is None or not await self._sandbox.available():
            raise SandboxUnavailableError(
                "The analysis sandbox is unavailable, so a report cannot be computed "
                "right now. Analysis never runs outside the sandbox."
            )

        tables = [t for t in await self._tables.list_for_workspace(workspace_id) if t.row_count > 0]
        if not tables:
            raise ValidationError(
                "There are no spreadsheets in this workspace to build a report from. "
                "Upload a CSV or spreadsheet and try again."
            )
        tables = sorted(tables, key=lambda t: t.row_count, reverse=True)[:MAX_DATASETS]

        used: set[str] = set()
        datasets: list[SandboxDataset] = []
        mapping: list[tuple[str, str]] = []
        for table in tables:
            variable = _variable_name(table.name, used)
            content = await self._storage.get(table.storage_key)
            datasets.append(
                SandboxDataset(variable=variable, filename=f"{variable}.csv", content=content)
            )
            mapping.append((table.name, variable))

        result = await self._sandbox.run(
            code=build_profiler_code(mapping), datasets=datasets, limits=self._limits
        )
        if not result.success:
            raise ValidationError(
                (result.error or "The workspace data could not be profiled.")[:500]
            )

        profile = result.scalars.get("result") or {}
        report, tokens = await self._compose(profile, focus, preferred_model)

        await self._usage.record(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            endpoint="workspace.report",
            model=report.model_used,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            latency_ms=result.execution_ms,
            success=True,
        )
        log.info(
            "workspace_report_generated",
            workspace_id=str(workspace_id),
            datasets=len(mapping),
            sections=len(report.sections),
        )
        return report

    async def _compose(
        self,
        profile: dict[str, object],
        focus: str | None,
        preferred_model: str | None,
    ) -> tuple[ExecutiveReport, tuple[int, int]]:
        """Turn computed evidence into a validated report contract.

        The model authors narrative and chart bindings; the computed series are
        attached here from the profile, and any chart whose fields do not match
        a real computed series is discarded.
        """
        series_by_key = {
            series["key"]: series
            for dataset in profile.get("datasets", [])
            if isinstance(dataset, dict)
            for series in dataset.get("series", [])
            if isinstance(series, dict) and series.get("key")
        }
        kpi_values = {
            kpi["key"]: kpi["value"]
            for dataset in profile.get("datasets", [])
            if isinstance(dataset, dict)
            for kpi in dataset.get("kpis", [])
            if isinstance(kpi, dict) and kpi.get("key") and kpi.get("value") is not None
        }

        provider, spec = self._router.resolve(
            task=TaskType.SYNTHESIS, preferred_model=preferred_model
        )
        instruction = f"Focus: {focus}\n\n" if focus else ""
        completion = await provider.generate(
            messages=[
                ChatMessage(
                    role="user",
                    content=(
                        f"{instruction}Computed evidence:\n"
                        f"{json.dumps(profile, default=str)[:14000]}"
                    ),
                )
            ],
            model=spec.id,
            system=REPORT_PROMPT,
            max_tokens=3000,
            json_schema=_strict_json_schema(ReportPlan.model_json_schema()),
        )
        plan = ReportPlan.model_validate_json(completion.text)

        kpis = [
            ReportKpi(
                label=kpi.label,
                value=_format_kpi(kpi_values[kpi.source_key], kpi.format),
                context=kpi.context,
                tone=kpi.tone,
            )
            for kpi in plan.kpis
            if kpi.source_key in kpi_values
        ]

        sections = [self._validate_section(section, series_by_key) for section in plan.sections]
        referenced = {chart.series_key for section in sections for chart in section.charts}
        series = [
            ReportSeries(
                key=series_by_key[key]["key"],
                title=series_by_key[key].get("title", key),
                columns=[str(c) for c in series_by_key[key].get("columns", [])],
                rows=series_by_key[key].get("rows", []),
            )
            for key in referenced
            if key in series_by_key
        ]

        report = ExecutiveReport(
            title=plan.title,
            thesis=plan.thesis,
            heading_status=plan.heading_status,
            kpis=kpis,
            sections=sections,
            series=series,
            limits=plan.limits,
            model_used=completion.model,
        )
        return report, (completion.usage.input_tokens, completion.usage.output_tokens)

    @staticmethod
    def _validate_section(section: ReportSection, series_by_key: dict[str, dict]) -> ReportSection:
        valid = []
        for chart in section.charts:
            series = series_by_key.get(chart.series_key)
            if series is None:
                continue
            columns = {str(c) for c in series.get("columns", [])}
            fields = [chart.x.field, chart.y.field]
            if chart.color is not None:
                fields.append(chart.color.field)
            if all(field in columns for field in fields):
                valid.append(chart)
        section.charts = valid
        return section


def _format_kpi(value: object, fmt: str) -> str:
    """Render a computed number for the KPI strip in the model's chosen format."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)

    if fmt == "percent":
        return f"{number:.1f}%"
    if fmt == "currency":
        return f"${number:,.0f}"
    if fmt == "compact_currency":
        return f"${_compact(number)}"
    if fmt == "compact_number":
        return _compact(number)
    return f"{number:,.0f}"


def _compact(number: float) -> str:
    magnitude = abs(number)
    if magnitude >= 1e9:
        return f"{number / 1e9:.1f}B"
    if magnitude >= 1e6:
        return f"{number / 1e6:.1f}M"
    if magnitude >= 1e3:
        return f"{number / 1e3:.1f}K"
    return f"{number:.0f}"


def _variable_name(name: str, used: set[str]) -> str:
    """A unique, valid Python identifier for a table's mounted DataFrame."""
    base = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower() or "table"
    if base[0].isdigit():
        base = "t_" + base
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _strict_json_schema(schema: dict[str, object]) -> dict[str, object]:
    """Make Pydantic's schema acceptable to strict-output providers.

    Every property must appear in ``required`` and every object must reject
    extra properties. Mirrors the coercion `AnalysisService` applies.
    """

    def visit(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema
