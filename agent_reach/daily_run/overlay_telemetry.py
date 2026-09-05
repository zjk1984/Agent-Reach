# -*- coding: utf-8
"""Daily session overlay telemetry for weekly digest aggregation."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai

_SH_TZ = ZoneInfo("Asia/Shanghai")
_SCHEMA_VERSION = 2
_REGIME_RANK = {"defensive": 3, "neutral": 2, "supportive": 1}


def overlay_telemetry_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("overlay_telemetry") or {})
    return {
        "schema_version": int(raw.get("schema_version") or _SCHEMA_VERSION),
        "dual_write_db": raw.get("dual_write_db", True) is not False,
        "read_prefer_db": raw.get("read_prefer_db", True) is not False,
        "fail_loud": raw.get("fail_loud", False) is True,
    }


def _log_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "overlay_log"


def _log_path(day: date) -> Path:
    return _log_dir() / f"{day.isoformat()}.json"


def _merge_regime(a: str, b: str) -> str:
    left = str(a or "neutral")
    right = str(b or "neutral")
    return left if _REGIME_RANK.get(left, 2) >= _REGIME_RANK.get(right, 2) else right


def _empty_session_block() -> dict[str, Any]:
    return {
        "seen": False,
        "scan_count": 0,
        "last_merged_regime": "neutral",
        "threshold_patched": False,
        "last_at": None,
    }


def _new_daily_record(day: date) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "version": _SCHEMA_VERSION,
        "morning": _empty_session_block(),
        "afternoon": _empty_session_block(),
        "day_merged_regime": "neutral",
        "week_open_regime": None,
        "seed_regime": None,
        "symbol_gate_count_max": 0,
        "forecast_accuracy_defensive": False,
        "day_threshold_patched": False,
        "sources": [],
    }


def _coerce_v2_record(row: dict[str, Any], day: date) -> dict[str, Any]:
    if int(row.get("version") or 0) >= _SCHEMA_VERSION and row.get("morning"):
        out = dict(row)
        out.setdefault("date", day.isoformat())
        out.setdefault("version", _SCHEMA_VERSION)
        out.setdefault("morning", _empty_session_block())
        out.setdefault("afternoon", _empty_session_block())
        return out

    out = _new_daily_record(day)
    session = str(row.get("session") or "")
    block = out["morning"] if session == "morning" else out["afternoon"] if session == "afternoon" else None
    if block is None:
        return out

    regime = str(row.get("merged_regime") or "neutral")
    block["seen"] = True
    block["scan_count"] = 1
    block["last_merged_regime"] = regime
    block["threshold_patched"] = regime != "neutral"
    out["day_merged_regime"] = regime
    out["day_threshold_patched"] = block["threshold_patched"]
    out["week_open_regime"] = row.get("week_open_regime")
    out["seed_regime"] = row.get("seed_regime")
    out["symbol_gate_count_max"] = int(row.get("symbol_gate_count") or 0)
    out["forecast_accuracy_defensive"] = bool(row.get("forecast_accuracy_defensive"))
    return out


def _load_daily_record(day: date) -> dict[str, Any]:
    path = _log_path(day)
    if not path.is_file():
        return _new_daily_record(day)
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _new_daily_record(day)
    if not isinstance(row, dict):
        return _new_daily_record(day)
    return _coerce_v2_record(row, day)


def _save_daily_record(day: date, record: dict[str, Any]) -> Path:
    path = _log_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**record, "date": day.isoformat(), "version": _SCHEMA_VERSION}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _snapshot_from_ctx(
    settings: dict[str, Any],
    ctx: Any,
    *,
    scan_at: str,
) -> dict[str, Any]:
    runtime = settings.get("harness_runtime") or {}
    if is_dataclass(ctx):
        ctx_dict = asdict(ctx)
    elif isinstance(ctx, dict):
        ctx_dict = ctx
    else:
        ctx_dict = {"merged_regime": getattr(ctx, "merged_regime", "neutral")}

    session = str(ctx_dict.get("session") or "none")
    merged = str(ctx_dict.get("merged_regime") or "neutral")
    threshold_patched = merged != "neutral"

    sources: list[str] = []
    if ctx_dict.get("week_open_regime"):
        sources.append("week_open")
    if ctx_dict.get("seed_regime"):
        sources.append("close_seed")
    if session == "morning" and ctx_dict.get("session_regime"):
        sources.append("am_open")
    if session == "afternoon" and ctx_dict.get("session_regime"):
        sources.append("pm_session")
    if ctx_dict.get("forecast_accuracy_defensive"):
        sources.append("forecast_accuracy")

    return {
        "scan_at": scan_at,
        "session": session,
        "merged_regime": merged,
        "threshold_patched": threshold_patched,
        "week_open_regime": ctx_dict.get("week_open_regime"),
        "seed_regime": ctx_dict.get("seed_regime"),
        "session_regime": ctx_dict.get("session_regime"),
        "forecast_accuracy_defensive": bool(ctx_dict.get("forecast_accuracy_defensive")),
        "symbol_gate_count": len(ctx_dict.get("symbol_gates") or {}),
        "week_open_active": bool((runtime.get("week_open") or {}).get("active")),
        "am_open_active": bool((runtime.get("am_open") or {}).get("active")),
        "pm_session_active": bool((runtime.get("pm_session") or {}).get("active")),
        "sources": sources,
    }


def _merge_snapshot_into_daily(record: dict[str, Any], snap: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    session = str(snap.get("session") or "none")
    if session not in ("morning", "afternoon"):
        return out

    block = dict(out.get(session) or _empty_session_block())
    block["seen"] = True
    block["scan_count"] = int(block.get("scan_count") or 0) + 1
    block["last_merged_regime"] = str(snap.get("merged_regime") or "neutral")
    block["threshold_patched"] = bool(snap.get("threshold_patched")) or bool(block.get("threshold_patched"))
    block["last_at"] = snap.get("scan_at")
    out[session] = block

    out["day_merged_regime"] = _merge_regime(
        str(out.get("day_merged_regime") or "neutral"),
        str(snap.get("merged_regime") or "neutral"),
    )
    out["day_threshold_patched"] = bool(out.get("day_threshold_patched")) or bool(
        snap.get("threshold_patched")
    )
    if snap.get("week_open_regime") is not None:
        out["week_open_regime"] = snap.get("week_open_regime")
    if snap.get("seed_regime") is not None:
        out["seed_regime"] = snap.get("seed_regime")
    out["symbol_gate_count_max"] = max(
        int(out.get("symbol_gate_count_max") or 0),
        int(snap.get("symbol_gate_count") or 0),
    )
    out["forecast_accuracy_defensive"] = bool(out.get("forecast_accuracy_defensive")) or bool(
        snap.get("forecast_accuracy_defensive")
    )

    merged_sources = list(out.get("sources") or [])
    for src in snap.get("sources") or []:
        if src not in merged_sources:
            merged_sources.append(src)
    out["sources"] = merged_sources
    return out


def _trading_days_in_range(
    week_start: date,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
) -> list[date]:
    cfg = settings or {}
    days: list[date] = []
    cursor = week_start
    while cursor <= week_end:
        ok, _ = is_trading_day(cursor, settings=cfg)
        if ok:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _aggregate_from_daily_rows(
    rows: list[dict[str, Any]],
    *,
    week_start: date,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
    source: str = "file",
) -> dict[str, Any]:
    trading_days = _trading_days_in_range(week_start, week_end, settings)
    n_trading = len(trading_days)

    morning_days = 0
    afternoon_days = 0
    defensive_days = 0
    supportive_days = 0
    threshold_patch_days = 0
    symbol_gate_days = 0
    forecast_acc_days = 0

    for row in rows:
        morning = row.get("morning") or {}
        afternoon = row.get("afternoon") or {}
        if morning.get("seen"):
            morning_days += 1
        if afternoon.get("seen"):
            afternoon_days += 1
        regime = str(row.get("day_merged_regime") or "neutral")
        if regime == "defensive":
            defensive_days += 1
        elif regime == "supportive":
            supportive_days += 1
        if row.get("day_threshold_patched"):
            threshold_patch_days += 1
        if int(row.get("symbol_gate_count_max") or 0) > 0:
            symbol_gate_days += 1
        if row.get("forecast_accuracy_defensive"):
            forecast_acc_days += 1

    log_days = len(rows)
    coverage = (log_days / n_trading) if n_trading else 0.0
    if n_trading == 0:
        quality = "missing"
    elif log_days >= n_trading:
        quality = "ok"
    elif log_days > 0:
        quality = "partial"
    else:
        quality = "missing"

    return {
        "trading_days_in_range": n_trading,
        "log_days": log_days,
        "days": log_days,
        "morning_overlay_days": morning_days,
        "afternoon_overlay_days": afternoon_days,
        "defensive_days": defensive_days,
        "supportive_days": supportive_days,
        "threshold_patch_days": threshold_patch_days,
        "symbol_gate_days": symbol_gate_days,
        "forecast_accuracy_defensive_days": forecast_acc_days,
        "coverage_pct": round(coverage, 3),
        "data_quality": quality,
        "source": source,
    }


def _load_daily_rows_from_files(week_start: date, week_end: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    day = week_start
    while day <= week_end:
        path = _log_path(day)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                day += timedelta(days=1)
                continue
            if isinstance(raw, dict):
                rows.append(_coerce_v2_record(raw, day))
        day += timedelta(days=1)
    return rows


def _telemetry_fail(settings: Optional[dict[str, Any]], label: str, exc: Exception) -> None:
    if overlay_telemetry_cfg(settings).get("fail_loud"):
        try:
            from loguru import logger

            logger.warning("overlay telemetry {} failed: {}", label, exc)
        except ImportError:
            pass


def record_session_overlay(
    settings: dict[str, Any],
    ctx: Any,
    *,
    settings_for_cfg: Optional[dict[str, Any]] = None,
    scan_at: Optional[str] = None,
) -> None:
    cfg_settings = settings_for_cfg if settings_for_cfg is not None else settings
    day = today_shanghai()
    at = scan_at or datetime.now(_SH_TZ).isoformat()
    snap = _snapshot_from_ctx(settings, ctx, scan_at=at)
    if snap.get("session") == "none":
        return

    try:
        daily = _merge_snapshot_into_daily(_load_daily_record(day), snap)
        path = _save_daily_record(day, daily)
    except Exception as exc:
        _telemetry_fail(cfg_settings, "file_write", exc)
        return

    tcfg = overlay_telemetry_cfg(cfg_settings)
    if not tcfg.get("dual_write_db"):
        return
    try:
        from agent_reach.daily_run.storage.hooks import (
            on_session_overlay_daily,
            on_session_overlay_event,
        )

        on_session_overlay_event(snap, day=day.isoformat(), source_path=str(path))
        on_session_overlay_daily(day.isoformat(), daily, source_path=str(path))
    except Exception as exc:
        _telemetry_fail(cfg_settings, "db_dual_write", exc)


def aggregate_week_overlay_stats(
    week_start: date,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    tcfg = overlay_telemetry_cfg(settings)
    rows: list[dict[str, Any]] = []
    source = "empty"

    if tcfg.get("read_prefer_db"):
        try:
            from agent_reach.daily_run.storage.readers import read_session_overlay_daily_range

            db_rows = read_session_overlay_daily_range(week_start, week_end, settings=settings)
            if db_rows:
                rows = db_rows
                source = "db"
        except Exception:
            pass

    if not rows:
        file_rows = _load_daily_rows_from_files(week_start, week_end)
        if file_rows:
            rows = file_rows
            source = "file"

    if not rows:
        return {
            "trading_days_in_range": len(_trading_days_in_range(week_start, week_end, settings)),
            "log_days": 0,
            "days": 0,
            "morning_overlay_days": 0,
            "afternoon_overlay_days": 0,
            "defensive_days": 0,
            "supportive_days": 0,
            "threshold_patch_days": 0,
            "symbol_gate_days": 0,
            "forecast_accuracy_defensive_days": 0,
            "coverage_pct": 0.0,
            "data_quality": "missing",
            "source": "empty",
        }

    return _aggregate_from_daily_rows(
        rows,
        week_start=week_start,
        week_end=week_end,
        settings=settings,
        source=source,
    )


def render_week_overlay_stats_markdown(stats: dict[str, Any]) -> list[str]:
    """Render Saturday weekly card lines for session overlay telemetry."""
    log_days = int(stats.get("log_days") or stats.get("days") or 0)
    if log_days <= 0:
        return []

    trading_days = int(stats.get("trading_days_in_range") or 0)
    coverage = float(stats.get("coverage_pct") or 0.0)
    quality = str(stats.get("data_quality") or "partial")

    defensive = int(stats.get("defensive_days") or 0)
    supportive = int(stats.get("supportive_days") or 0)
    neutral = max(0, log_days - defensive - supportive)
    morning = int(stats.get("morning_overlay_days") or 0)
    afternoon = int(stats.get("afternoon_overlay_days") or 0)
    symbol_gate = int(stats.get("symbol_gate_days") or 0)
    forecast_def = int(stats.get("forecast_accuracy_defensive_days") or 0)
    patch_days = int(stats.get("threshold_patch_days") or 0)

    lines = [
        "## 📊 量化 Overlay",
        "",
    ]
    if trading_days > 0:
        pct_s = f"{coverage * 100:.0f}%"
        lines.append(f"- **覆盖**: 本周 {trading_days} 个交易日，有遥测 {log_days} 天（{pct_s}）")
    else:
        lines.append(f"- **记录天数**: {log_days} 天")
    lines.append(f"- **阈值调整**: {patch_days} 天 · **合并态** 防御 {defensive} · 进攻 {supportive} · 中性 {neutral}")
    lines.append(f"- **早盘 scan**: {morning} 天 · **午盘 scan**: {afternoon} 天")
    lines.append(f"- **个股门控**: {symbol_gate} 天 · **预测偏防守**: {forecast_def} 天")
    if quality != "ok":
        lines.append(f"- ⚠️ **数据质量**: {quality}（部分交易日可能无 intraday 遥测）")
    lines.extend(
        [
            "",
            (
                "> 08:00 早盘 / 12:30 午盘 scan 经 session_overlay 合并"
                " close seed、week_open 与 forecast 门控，统一调整当日 MSS 阈值。"
            ),
            "",
        ]
    )
    return lines
