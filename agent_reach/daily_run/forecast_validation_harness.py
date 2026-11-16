# -*- coding: utf-8
"""Weekly structured forecast validation — compact persistence + harness closure (AR-28 / phase B)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def validation_harness_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("week_forecast") or {})
    block = dict(raw.get("validation_harness") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "index_miss_streak_warn": max(1, int(block.get("index_miss_streak_warn", 2))),
        "benchmark_underperform_streak_warn": max(1, int(block.get("benchmark_underperform_streak_warn", 2))),
        "auto_tighten_deploy_on_streak": block.get("auto_tighten_deploy_on_streak", False) is True,
        "index_max_weeks": max(4, int(block.get("index_max_weeks", 52))),
    }


def validation_reports_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "reports" / "forecast_validation"


def validation_index_path() -> Path:
    return validation_reports_dir() / "index.json"


def validation_week_path(week_start: str) -> Path:
    ws = str(week_start or "")[:10]
    return validation_reports_dir() / f"{ws}.json"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_verification_row(verification: dict[str, Any]) -> Optional[dict[str, Any]]:
    for row in verification.get("rows") or []:
        pred = str(row.get("prediction") or "")
        if "大盘" in pred or "沪深" in pred or "300" in pred:
            return row
    rows = list(verification.get("rows") or [])
    return rows[0] if rows else None


def _index_direction_hit(
    market: dict[str, Any],
    actual_pct: Optional[float],
) -> Optional[bool]:
    if actual_pct is None:
        return None
    from agent_reach.daily_run.forecast_tracking import _direction_hit

    return _direction_hit(market, actual_pct)


def build_compact_validation_record(
    verification: dict[str, Any],
    forecast: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compact weekly validation payload for reports dir / storage."""
    structured = forecast.get("structured_predictions") or {}
    market = dict(structured.get("market") or {})
    metrics = verification.get("metrics") or {}
    market_row = _market_verification_row(verification) or {}

    ws = str(verification.get("week_start") or forecast.get("week_start") or "")[:10]
    we = str(verification.get("week_end") or forecast.get("week_end") or "")[:10]

    band_low = _optional_float(market.get("change_pct_low"))
    band_high = _optional_float(market.get("change_pct_high"))
    index_hit = market_row.get("hit")

    bench_pct: Optional[float] = None
    try:
        from agent_reach.daily_run.weekly_card_metrics import fetch_benchmark_weekly_return

        if ws and we:
            bench = fetch_benchmark_weekly_return(
                date.fromisoformat(ws),
                date.fromisoformat(we),
                settings=settings,
            )
            if bench.get("ok"):
                bench_pct = _optional_float(bench.get("return_pct"))
    except (ValueError, TypeError):
        bench_pct = None

    index_direction_hit = _index_direction_hit(market, bench_pct)

    underperform: dict[str, Any] = {}
    if we:
        try:
            from agent_reach.daily_run.weekly_card_metrics import compute_weekly_benchmark_underperform_streak

            excess = None
            if bench_pct is not None and metrics.get("operation_returns"):
                op = metrics.get("operation_returns") or {}
                hold = _optional_float(op.get("hold_return_pct"))
                if hold is not None:
                    excess = round(hold - bench_pct, 2)
            underperform = compute_weekly_benchmark_underperform_streak(
                date.fromisoformat(we),
                settings=settings,
                current_week_excess=excess,
            )
        except (ValueError, TypeError):
            underperform = {}

    record: dict[str, Any] = {
        "schema": "forecast_validation_v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "week_start": ws,
        "week_end": we,
        "summary": {
            "accuracy_pct": verification.get("accuracy_pct"),
            "interval_hit_rate_pct": metrics.get("interval_hit_rate_pct"),
            "direction_accuracy_pct": metrics.get("direction_accuracy_pct"),
            "avg_deviation_pct": verification.get("avg_deviation_pct"),
            "interval_hits": metrics.get("interval_hits"),
            "interval_total": metrics.get("interval_total"),
            "direction_hits": metrics.get("direction_hits"),
            "direction_total": metrics.get("direction_total"),
        },
        "index": {
            "name": market.get("index_name") or "沪深300",
            "band_low_pct": band_low,
            "band_high_pct": band_high,
            "band_hit": index_hit,
            "actual_pct": bench_pct,
            "direction_hit": index_direction_hit,
            "macro_downside_extra_pct": _optional_float(market.get("macro_downside_extra_pct")),
            "verify": market_row.get("verify"),
            "deviation": market_row.get("deviation"),
        },
        "benchmark_underperform": {
            "underperform_week_streak": underperform.get("underperform_week_streak"),
            "threshold_pct": underperform.get("threshold_pct"),
        },
    }
    return record


def load_validation_index(*, max_weeks: Optional[int] = None) -> list[dict[str, Any]]:
    path = validation_index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = list(data.get("weeks") or [])
    if max_weeks is not None and max_weeks > 0:
        return rows[-max_weeks:]
    return rows


def save_validation_index(rows: list[dict[str, Any]], *, max_weeks: int = 52) -> Path:
    path = validation_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = rows[-max_weeks:] if max_weeks > 0 else rows
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "weeks": trimmed,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def index_band_miss_streak(
    index_rows: list[dict[str, Any]],
    *,
    current_band_hit: Optional[bool] = None,
) -> int:
    """Trailing consecutive weeks where CSI300 structured band missed."""
    if current_band_hit is True:
        return 0
    streak = 1 if current_band_hit is False else 0
    for row in reversed(index_rows):
        hit = row.get("index_band_hit")
        if hit is False:
            streak += 1
        elif hit is True:
            break
        else:
            break
    return streak


def _index_compact_row(record: dict[str, Any]) -> dict[str, Any]:
    idx = record.get("index") or {}
    return {
        "week_start": record.get("week_start"),
        "week_end": record.get("week_end"),
        "index_band_hit": idx.get("band_hit"),
        "index_direction_hit": idx.get("direction_hit"),
        "macro_downside_extra_pct": idx.get("macro_downside_extra_pct"),
        "interval_hit_rate_pct": (record.get("summary") or {}).get("interval_hit_rate_pct"),
        "recorded_at": record.get("recorded_at"),
    }


def compute_index_band_miss_streak(
    record: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> int:
    cfg = validation_harness_cfg(settings)
    prior = [
        r
        for r in load_validation_index(max_weeks=cfg["index_max_weeks"])
        if str(r.get("week_start") or "") != str(record.get("week_start") or "")
    ]
    return index_band_miss_streak(prior, current_band_hit=record.get("index", {}).get("band_hit"))


def build_deploy_tighten_signal(
    record: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Harness-friendly deploy-tighten hint; auto-apply only when config enables it."""
    cfg = validation_harness_cfg(settings)
    idx = record.get("index") or {}
    bench = record.get("benchmark_underperform") or {}

    index_streak = compute_index_band_miss_streak(record, settings=settings)
    bench_streak = int(bench.get("underperform_week_streak") or 0)

    reasons: list[str] = []
    if index_streak >= cfg["index_miss_streak_warn"]:
        reasons.append(f"指数预测区间连续未命中 {index_streak} 周")
    if bench_streak >= cfg["benchmark_underperform_streak_warn"]:
        reasons.append(f"组合连续 {bench_streak} 周未跑赢沪深300")

    active = bool(reasons)
    signal = {
        "active": active,
        "auto_tighten_enabled": cfg["auto_tighten_deploy_on_streak"],
        "index_miss_streak": index_streak,
        "index_miss_streak_warn": cfg["index_miss_streak_warn"],
        "benchmark_underperform_week_streak": bench_streak,
        "benchmark_streak_warn": cfg["benchmark_underperform_streak_warn"],
        "reasons": reasons,
        "harness_hint": (
            "周预测校验：连续 miss / 跑输基准 — 建议收紧 deploy 上限、维持现金护栏（见 harness policy）"
            if active
            else ""
        ),
        "playbook": [
            "调高 cash_ratio 护栏或降低 deploy_cap（effective profile）",
            "运行 python3 -m agent_reach.cli daily-run optimize (forecast_calibrate)",
        ]
        if active
        else [],
        "macro_downside_extra_pct": idx.get("macro_downside_extra_pct"),
    }
    if active and not cfg["auto_tighten_deploy_on_streak"]:
        signal["apply"] = False
        signal["note"] = "auto_tighten_deploy_on_streak=false — signal only, no settings mutation"
    elif active:
        signal["apply"] = True
        signal["note"] = "auto_tighten enabled — consumer must apply via harness (not inline here)"
    return signal


def persist_forecast_validation_closure(
    verification: dict[str, Any],
    forecast: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Write compact record + index; optional SQLite L2 + harness tighten signal."""
    cfg = validation_harness_cfg(settings)
    if not cfg["enabled"]:
        return {"skipped": True, "reason": "validation_harness disabled"}

    if not verification.get("rows"):
        return {"skipped": True, "reason": "no verification rows"}

    record = build_compact_validation_record(verification, forecast, settings=settings)
    signal = build_deploy_tighten_signal(record, settings=settings)
    record["harness_signal"] = signal

    week_path = validation_week_path(str(record.get("week_start") or ""))
    week_path.parent.mkdir(parents=True, exist_ok=True)
    week_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_rows = load_validation_index(max_weeks=cfg["index_max_weeks"])
    compact = _index_compact_row(record)
    index_rows = [r for r in index_rows if r.get("week_start") != compact.get("week_start")]
    index_rows.append(compact)
    index_rows.sort(key=lambda r: str(r.get("week_start") or ""))
    save_validation_index(index_rows, max_weeks=cfg["index_max_weeks"])

    try:
        from agent_reach.daily_run.storage.hooks import on_forecast_validation

        on_forecast_validation(record, source_path=str(week_path), settings=settings)
    except Exception:
        pass

    return {
        "skipped": False,
        "path": str(week_path),
        "week_start": record.get("week_start"),
        "record": record,
        "harness_signal": signal,
    }


def render_validation_harness_summary_markdown(record: dict[str, Any]) -> str:
    """One-line summary for internal markdown / quant digest extensions."""
    idx = record.get("index") or {}
    summary = record.get("summary") or {}
    sig = record.get("harness_signal") or {}
    hit = idx.get("band_hit")
    hit_s = "命中" if hit is True else ("未命中" if hit is False else "—")
    acc = summary.get("accuracy_pct")
    acc_s = f"{float(acc):.0f}%" if acc is not None else "—"
    parts = [
        f"指数区间{hit_s}",
        f"结构化准确率 {acc_s}",
    ]
    extra = idx.get("macro_downside_extra_pct")
    if extra:
        parts.append(f"macro_downside +{float(extra):.1f}pp")
    if sig.get("active"):
        parts.append(f"⚠️ {'；'.join(sig.get('reasons') or [])}")
    return " · ".join(parts)