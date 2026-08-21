"""Deterministic dataset profiling, executed inside the sandbox.

The profiler is *our* code, not model-generated. It runs against every
spreadsheet in a workspace and emits computed KPIs and small aggregated series
as one JSON object. A single generation then turns that computed evidence into
the executive report, so every number in the report traces to a real
computation rather than the model's imagination.

Running it in the sandbox — the same isolated, no-network, resource-capped
boundary that model code runs in — keeps a large or malformed spreadsheet from
tying up an API worker, and reuses the one execution path that is already
hardened.
"""

from __future__ import annotations

# Executed inside the sandbox. Only `pd`/`np` and the mounted DataFrames exist;
# `_FRAMES` is injected as a header by `build_profiler_code`.
_PROFILER_BODY = r"""
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return round(f, 4)


def _kind(frame, col):
    series = frame[col]
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    name = str(col).lower()
    hints = ("date", "month", "week", "year", "quarter", "period", "day", "time")
    if any(t in name for t in hints):
        return "temporal"
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().mean() > 0.7:
        return "temporal"
    return "categorical"


def _primary(numeric):
    keywords = (
        "revenue", "amount", "sales", "value",
        "total", "count", "hours", "tickets", "orders",
    )

    def score(col):
        low = col.lower()
        for i, kw in enumerate(keywords):
            if kw in low:
                return i
        return 99

    return sorted(numeric, key=score)[0] if numeric else None


def _attainment_pairs(numeric):
    pairs = []
    for measure in numeric:
        for target in numeric:
            if target == measure:
                continue
            tl, ml = target.lower(), measure.lower()
            base = ml.replace("_", "")
            if ("target" in tl and base in tl.replace("target", "").replace("_", "")) \
                    or tl == "target_" + ml or tl == ml + "_target":
                pairs.append((measure, target))
    return pairs


def _profile(name, variable, frame):
    frame = frame.copy()
    columns = list(frame.columns)
    kinds = {c: _kind(frame, c) for c in columns}
    numeric = [c for c in columns if kinds[c] == "numeric"]
    temporal = [c for c in columns if kinds[c] == "temporal"]
    categorical = [c for c in columns if kinds[c] == "categorical"]
    primary = _primary(numeric)

    kpis = [
        {"key": name + "|rows", "label": name + " rows",
         "value": int(len(frame)), "unit": "count"}
    ]
    for col in numeric[:6]:
        kpis.append({"key": name + "|" + col + "|total", "label": col + " total",
                     "value": _num(frame[col].sum()), "unit": "number"})
        kpis.append({"key": name + "|" + col + "|avg", "label": col + " avg",
                     "value": _num(frame[col].mean()), "unit": "number"})
    for measure, target in _attainment_pairs(numeric):
        denom = frame[target].sum()
        if denom:
            kpis.append({"key": name + "|" + measure + "|attainment",
                         "label": measure + " attainment",
                         "value": _num(frame[measure].sum() / denom * 100), "unit": "percent"})

    series = []
    if primary and temporal:
        tcol = temporal[0]
        window = frame[[tcol, primary]].copy()
        window[tcol] = pd.to_datetime(window[tcol], errors="coerce")
        window = window.dropna(subset=[tcol])
        if len(window):
            grouped = window.groupby(window[tcol].dt.to_period("M"))[primary].sum().reset_index()
            grouped[tcol] = grouped[tcol].astype(str)
            rows = [[str(a), _num(b)] for a, b in grouped.values.tolist()][:60]
            series.append({"key": name + "__" + primary + "_over_time",
                           "title": primary + " over time",
                           "columns": [tcol, primary], "rows": rows})

    for cat in categorical:
        distinct = frame[cat].nunique(dropna=True)
        if primary and 1 < distinct <= 12:
            grouped = (
                frame.groupby(cat)[primary].sum().reset_index()
                .sort_values(primary, ascending=False)
            )
            rows = [[str(a), _num(b)] for a, b in grouped.values.tolist()][:12]
            series.append({"key": name + "__" + primary + "_by_" + cat,
                           "title": primary + " by " + cat,
                           "columns": [cat, primary], "rows": rows})
        if len([s for s in series if s["key"].startswith(name + "__")]) >= 4:
            break

    return {
        "name": name,
        "variable": variable,
        "row_count": int(len(frame)),
        "columns": [{"name": str(c), "kind": kinds[c]} for c in columns],
        "primary_measure": primary,
        "kpis": [k for k in kpis if k.get("value") is not None],
        "series": series,
    }


_out = {"datasets": []}
for _name, _variable, _frame in _FRAMES:
    try:
        _out["datasets"].append(_profile(_name, _variable, _frame))
    except Exception as _exc:  # one bad sheet must not sink the whole report
        _out["datasets"].append({"name": _name, "variable": _variable, "error": str(_exc)[:300]})

result = _out
"""


def build_profiler_code(datasets: list[tuple[str, str]]) -> str:
    """Assemble the profiler program for a specific set of datasets.

    `datasets` is a list of ``(display_name, variable)`` pairs. The variables
    must be the exact DataFrame names the sandbox mounts, so the header can
    reference each mounted frame directly.
    """
    entries = ", ".join(f"({name!r}, {variable!r}, {variable})" for name, variable in datasets)
    return f"_FRAMES = [{entries}]\n{_PROFILER_BODY}"
