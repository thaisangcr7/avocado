"""Whole-workspace report composition: grounding, validation, chart binding."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.clients.llm.router import ModelRouter, ProviderRegistry
from app.clients.sandbox.base import SandboxLimits, SandboxResult
from app.core.config import Settings
from app.services.report_service import ReportService, _variable_name
from tests.fakes import FakeLLMProvider, FakeSandbox

PROFILE = {
    "datasets": [
        {
            "name": "revenue_by_region.csv",
            "variable": "revenue_by_region",
            "row_count": 800,
            "primary_measure": "revenue",
            "kpis": [
                {
                    "key": "revenue_by_region|revenue|total",
                    "label": "revenue total",
                    "value": 25400000,
                    "unit": "number",
                }
            ],
            "series": [
                {
                    "key": "revenue_by_region__revenue_by_region",
                    "title": "revenue by region",
                    "columns": ["region", "revenue"],
                    "rows": [["East", 7120000], ["North", 7030000]],
                }
            ],
        }
    ]
}

PLAN = {
    "title": "Northwind HQ Executive Briefing",
    "thesis": "Revenue is ahead of plan, but the support backlog needs a decision.",
    "heading_status": "watch",
    "kpis": [{"label": "Revenue", "value": "$25.4M", "context": "vs target", "tone": "positive"}],
    "sections": [
        {
            "title": "Revenue & Growth",
            "status": "on_course",
            "narrative": "East leads at 115% of target while North trails.",
            "charts": [
                {
                    "title": "Revenue by region",
                    "description": None,
                    "mark": "bar",
                    "series_key": "revenue_by_region__revenue_by_region",
                    "x": {"field": "region", "type": "nominal", "title": "Region", "format": None},
                    "y": {
                        "field": "revenue",
                        "type": "quantitative",
                        "title": "Revenue",
                        "format": None,
                    },
                    "color": None,
                },
                {
                    "title": "Dropped: unknown series",
                    "description": None,
                    "mark": "bar",
                    "series_key": "does_not_exist",
                    "x": {"field": "x", "type": "nominal", "title": None, "format": None},
                    "y": {"field": "y", "type": "quantitative", "title": None, "format": None},
                    "color": None,
                },
            ],
        }
    ],
    "limits": ["Only monthly aggregates were available."],
}


class _NoopUsage:
    async def record(self, **_kwargs: object) -> None:
        return None


def _service(*, sandbox: FakeSandbox, llm: FakeLLMProvider) -> ReportService:
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.register(llm, make_default=True)
    tables = SimpleNamespace(
        list_for_workspace=lambda _workspace_id: _tables_result(),
    )
    storage = SimpleNamespace(get=lambda _key: _storage_result())
    return ReportService(
        tables=tables,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        sandbox=sandbox,
        limits=SandboxLimits(
            timeout_seconds=30, memory_mb=512, cpus=1.0, max_output_bytes=1_000_000
        ),
        router=ModelRouter(registry),
        usage=_NoopUsage(),  # type: ignore[arg-type]
    )


async def _tables_result() -> list[SimpleNamespace]:
    return [SimpleNamespace(name="revenue_by_region.csv", row_count=800, storage_key="k1")]


async def _storage_result() -> bytes:
    return b"region,revenue\nEast,1\n"


@pytest.mark.asyncio
async def test_report_binds_charts_and_grounds_series():
    sandbox = FakeSandbox(
        results=[SandboxResult(success=True, scalars={"result": PROFILE}, execution_ms=12)]
    )
    llm = FakeLLMProvider(responses=[json.dumps(PLAN)])
    service = _service(sandbox=sandbox, llm=llm)

    report = await service.generate(
        workspace_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        focus=None,
        preferred_model=None,
    )

    assert report.title == "Northwind HQ Executive Briefing"
    assert report.heading_status == "watch"
    assert len(report.kpis) == 1
    # The unknown-series chart is dropped; only the valid binding survives.
    assert len(report.sections) == 1
    assert len(report.sections[0].charts) == 1
    assert report.sections[0].charts[0].series_key == "revenue_by_region__revenue_by_region"
    # The computed series is attached from the profile, not authored by the model.
    assert len(report.series) == 1
    assert report.series[0].rows == [["East", 7120000], ["North", 7030000]]
    assert report.model_used


def test_variable_name_is_unique_and_valid():
    used: set[str] = set()
    assert _variable_name("revenue_by_region.csv", used) == "revenue_by_region_csv"
    assert _variable_name("revenue_by_region.csv", used) == "revenue_by_region_csv_2"
    assert _variable_name("123 numbers", used) == "t_123_numbers"
