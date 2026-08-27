# -*- coding: utf-8 -*-
"""Rejected strategy guardrails (DSH rejected Agent Notes style)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_REJECTED_PATH = Path.home() / ".agent-reach" / "daily_run" / "rejected_strategies.jsonl"
_ARCHIVE_PATH = _REJECTED_PATH.parent / "rejected_strategies_archive.jsonl"


def rejected_path() -> Path:
    return _REJECTED_PATH


def archive_path() -> Path:
    return _ARCHIVE_PATH


def _normalize_title(title: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", str(title or "").lower())
    return raw[:64]


def _rejected_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = dict((settings or {}).get("rejected_strategies") or {})
    whatif = dict(cfg.get("weekly_whatif") or {})
    return {
        "harness_evolve": cfg.get("harness_evolve", True),
        "weekly_refresh": cfg.get("weekly_refresh", True),
        "active_week_only": cfg.get("active_week_only", True),
        "archive_expired": cfg.get("archive_expired", True),
        "auto_add_from_weekly": cfg.get("auto_add_from_weekly", True),
        "buy_notional_delta_cny": float(whatif.get("buy_notional_delta_cny", 5000)),
        "sell_pnl_delta_cny": float(whatif.get("sell_pnl_delta_cny", 200)),
        "friction_pass_min": int(whatif.get("friction_pass_min", 2)),
        "trend_mismatch_min": int(whatif.get("trend_mismatch_min", 2)),
        "intraday_sell_missed_min": int(whatif.get("intraday_sell_missed_min", 2)),
        "require_whatif_for_macro": whatif.get("require_whatif_for_macro", True) is not False,
        "deep_loss_lag_count_min": int(whatif.get("deep_loss_lag_count_min", 1)),
        "deep_loss_share_delta_min": int(whatif.get("deep_loss_share_delta_min", 100)),
        "sell_threshold_missed_min": int(
            whatif.get("sell_threshold_missed_min", whatif.get("intraday_sell_missed_min", 2))
        ),
        "forecast_divergence_days_min": int(whatif.get("forecast_divergence_days_min", 3)),
        "optimizer_score_delta_min": float(whatif.get("optimizer_score_delta_min", 0.05)),
        "kronos_blocked_signals_min": int(whatif.get("kronos_blocked_signals_min", 2)),
    }


def _parse_iso_date(raw: str) -> Optional[date]:
    text = str(raw or "")[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _record_week_bounds(row: dict[str, Any], as_of: Optional[date] = None) -> tuple[str, str]:
    ws = str(row.get("week_start") or "")[:10]
    we = str(row.get("week_end") or "")[:10]
    if ws and we:
        return ws, we
    created = _parse_iso_date(str(row.get("created_at") or ""))
    if created is not None:
        from agent_reach.daily_run.weekly_report import trading_week_range

        monday, friday = trading_week_range(created)
        return monday.isoformat(), friday.isoformat()
    from agent_reach.daily_run.weekly_report import trading_week_range

    monday, friday = trading_week_range(as_of)
    return monday.isoformat(), friday.isoformat()


def _record_in_week(
    row: dict[str, Any],
    week_start: date,
    week_end: date,
    *,
    as_of: Optional[date] = None,
) -> bool:
    ws_s, we_s = _record_week_bounds(row, as_of)
    ws = _parse_iso_date(ws_s)
    we = _parse_iso_date(we_s)
    if ws is None or we is None:
        return False
    return ws == week_start and we == week_end


def load_rejected_records(*, limit: int = 200, settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    try:
        from agent_reach.daily_run.storage.config import storage_db_reads_allowed
        from agent_reach.daily_run.storage.readers import read_rejected_strategies

        if storage_db_reads_allowed(settings, file_path=_REJECTED_PATH):
            from agent_reach.daily_run.settings import load_settings

            rows = read_rejected_strategies(settings=load_settings(), limit=limit)
            if rows:
                return rows[-limit:]
    except Exception:
        pass
    if not _REJECTED_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in _REJECTED_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-limit:]


def load_active_rejected_records(
    *,
    as_of: Optional[date] = None,
    limit: int = 200,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    cfg = _rejected_cfg(settings)
    rows = load_rejected_records(limit=limit, settings=settings)
    if not cfg.get("active_week_only", True):
        return rows
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.weekly_report import trading_week_range

    ref = as_of or today_shanghai()
    week_start, week_end = trading_week_range(ref)
    active = [row for row in rows if _record_in_week(row, week_start, week_end, as_of=ref)]
    return active[-limit:]


def rejected_title_keys(settings: Optional[dict[str, Any]] = None) -> set[str]:
    keys: set[str] = set()
    for row in load_active_rejected_records(settings=settings):
        key = _normalize_title(str(row.get("title") or ""))
        if key:
            keys.add(key)
    return keys


def is_rejected_title(title: str, settings: Optional[dict[str, Any]] = None) -> bool:
    key = _normalize_title(title)
    return bool(key) and key in rejected_title_keys(settings)


_BUY_BLOCK_PHRASES: tuple[str, ...] = (
    "接飞刀",
    "加大仓位",
    "激进建仓",
    "满仓进攻",
    "逆势加仓",
)


def trade_blocked_by_rejected(
    action: str,
    *,
    code: str = "",
    name: str = "",
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return rejected strategy title if trade action should be blocked."""
    harness_cfg = dict((settings or {}).get("harness") or {})
    if harness_cfg.get("runtime_rejected_guard", True) is False:
        return None

    action = str(action or "").lower()
    if action != "buy":
        return None

    for label in (name, code):
        if label and is_rejected_title(str(label), settings=settings):
            return str(label)

    for row in load_active_rejected_records(settings=settings):
        title = str(row.get("title") or "")
        reason = str(row.get("reason") or "")
        blob = f"{title} {reason}"
        if any(p in blob for p in _BUY_BLOCK_PHRASES):
            return title or reason
    return None


def _next_id(existing: list[dict[str, Any]]) -> str:
    max_n = 0
    for row in existing:
        raw = str(row.get("id") or "")
        match = re.search(r"(\d+)$", raw)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"rej_{max_n + 1:04d}"


def _find_same_week_title(
    title: str,
    *,
    week_start: str,
    week_end: str,
    rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    key = _normalize_title(title)
    if not key:
        return None
    for row in rows:
        if _normalize_title(str(row.get("title") or "")) != key:
            continue
        if str(row.get("week_start") or "")[:10] == week_start[:10] and str(row.get("week_end") or "")[:10] == week_end[:10]:
            return row
    return None


def _write_rejected_records(rows: list[dict[str, Any]]) -> None:
    _REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REJECTED_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_archive_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    _ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    archived_at = datetime.now(timezone.utc).isoformat()
    with open(_ARCHIVE_PATH, "a", encoding="utf-8") as f:
        for row in rows:
            payload = dict(row)
            payload.setdefault("archived_at", archived_at)
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return len(rows)


def _weekly_loss(report: dict[str, Any]) -> bool:
    pnl_pct = report.get("weekly_pnl_pct")
    if pnl_pct is None:
        return False
    return float(pnl_pct) < 0


def _buy_block_title(blob: str, name: str = "") -> str:
    if "接飞刀" in blob:
        return "禁止接飞刀追涨"
    if name:
        return f"禁止{name}逆势加仓"
    return "禁止逆势加仓"


def _candidates_from_buy_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Return (title, reason, source_tag) from buy what-if."""
    out: list[tuple[str, str, str]] = []
    buy = report.get("buy_rules_whatif") or {}
    if buy.get("skipped"):
        return out

    for row in buy.get("rows") or []:
        actual = int(row.get("actual_bought") or 0)
        hypo = int(row.get("hypothetical_bought") or 0)
        block = str(row.get("block_reason") or "").strip()
        if actual <= 0 or actual <= hypo:
            continue
        name = str(row.get("name") or row.get("code") or "").strip()
        blob = f"{block} {name}"
        if not any(p in blob for p in _BUY_BLOCK_PHRASES):
            continue
        title = _buy_block_title(blob, name)
        reason = block or f"买入 what-if：基准多买 {actual - hypo} 股（自进化阻断）"
        out.append((title, reason, "buy_whatif"))

    if _weekly_loss(report):
        delta = float(buy.get("buy_notional_delta") or 0)
        threshold = float(cfg.get("buy_notional_delta_cny", 5000))
        if delta <= -threshold:
            pnl_pct = float(report.get("weekly_pnl_pct") or 0)
            out.append(
                (
                    "禁止接飞刀追涨",
                    f"买入 what-if：本周亏损 {pnl_pct:+.2f}% 且基准超自进化 ¥{abs(delta):,.0f}",
                    "buy_whatif",
                )
            )
    return out


def _candidates_from_sell_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    sell = report.get("sell_rules_whatif") or {}
    if sell.get("skipped") or not _weekly_loss(report):
        return out

    actual_pnl = float(sell.get("actual_realized_pnl") or 0)
    hypo_pnl = float(sell.get("hypothetical_realized_pnl") or 0)
    pnl_delta = float(sell.get("realized_pnl_delta") or 0)
    threshold = float(cfg.get("sell_pnl_delta_cny", 200))

    for row in sell.get("rows") or []:
        actual = int(row.get("actual_sold") or 0)
        hypo = int(row.get("hypothetical_sold") or 0)
        if actual <= hypo:
            continue
        name = str(row.get("name") or row.get("code") or "").strip()
        block = str(row.get("block_reason") or "").strip()
        reason = block or f"卖出 what-if：基准多卖 {actual - hypo} 股"
        title = _buy_block_title(f"逆势加仓 {reason}", name)
        out.append((title, f"{reason}，亏损后不宜逆势加仓", "sell_whatif"))

    if pnl_delta <= -threshold:
        out.append(
            (
                "禁止接飞刀追涨",
                f"卖出 what-if：基准已实现 {actual_pnl:+,.0f} vs 自进化 {hypo_pnl:+,.0f}（差 {pnl_delta:+,.0f}），逆势回补已证伪",
                "sell_whatif",
            )
        )
    return out


def _candidates_from_intraday_friction_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    friction = report.get("intraday_friction_whatif") or {}
    if friction.get("skipped") or not _weekly_loss(report):
        return out

    friction_pass = int(friction.get("friction_would_pass") or 0)
    trend_miss = int(friction.get("trend_mismatch") or 0)
    pass_min = int(cfg.get("friction_pass_min", 2))
    trend_min = int(cfg.get("trend_mismatch_min", 2))

    if friction_pass >= pass_min:
        out.append(
            (
                "禁止接飞刀追涨",
                f"盘中摩擦 what-if：自进化可放行 {friction_pass} 次，摩擦门槛过严导致错失后不宜追涨",
                "intraday_friction_whatif",
            )
        )
    if trend_miss >= trend_min:
        out.append(
            (
                "禁止接飞刀追涨",
                f"盘中摩擦 what-if：趋势误判 {trend_miss} 次，逆势加仓已证伪",
                "intraday_friction_whatif",
            )
        )
    return out


def _candidates_from_intraday_sell_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    intraday_sell = report.get("intraday_sell_whatif") or {}
    if intraday_sell.get("skipped") or not _weekly_loss(report):
        return out

    missed = int(intraday_sell.get("missed_sell_signals") or 0)
    missed_min = int(cfg.get("intraday_sell_missed_min", 2))
    delta = int(intraday_sell.get("sell_share_delta") or 0)
    if missed >= missed_min:
        out.append(
            (
                "禁止接飞刀追涨",
                f"盘中卖出 what-if：错失防御卖出 {missed} 次，卖晚后追涨已证伪",
                "intraday_sell_whatif",
            )
        )
    elif delta < -500:
        out.append(
            (
                "禁止接飞刀追涨",
                f"盘中卖出 what-if：基准少卖 {abs(delta)} 股，亏损后不宜接飞刀",
                "intraday_sell_whatif",
            )
        )
    return out


def _candidates_from_deep_loss_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not _weekly_loss(report):
        return out
    sell = report.get("sell_rules_whatif") or {}
    if sell.get("skipped"):
        return out

    deep_rows = [row for row in sell.get("rows") or [] if row.get("is_deep_loss")]
    lag_count = sum(
        1
        for row in deep_rows
        if int(row.get("hypothetical_sold") or 0) > int(row.get("actual_sold") or 0)
    )
    share_delta = sum(max(0, int(row.get("share_delta") or 0)) for row in deep_rows)
    if lag_count >= int(cfg.get("deep_loss_lag_count_min", 1)) or share_delta >= int(
        cfg.get("deep_loss_share_delta_min", 100)
    ):
        out.append(
            (
                "禁止延迟深亏止损",
                f"深亏 what-if：{lag_count} 只处置滞后，基准应多卖 {share_delta} 股",
                "deep_loss_whatif",
            )
        )
    return out


def _candidates_from_sell_threshold_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not _weekly_loss(report):
        return out

    sell = report.get("sell_rules_whatif") or {}
    intraday_sell = report.get("intraday_sell_whatif") or {}
    missed = (
        int(intraday_sell.get("missed_sell_signals") or 0)
        if not intraday_sell.get("skipped")
        else 0
    )
    pnl_delta = float(sell.get("realized_pnl_delta") or 0) if not sell.get("skipped") else 0.0
    missed_min = int(cfg.get("sell_threshold_missed_min", 2))
    pnl_thr = float(cfg.get("sell_pnl_delta_cny", 200))
    if missed < missed_min and pnl_delta > -pnl_thr:
        return out

    parts: list[str] = []
    if missed >= missed_min:
        parts.append(f"盘中 scan 错失 {missed} 次")
    if pnl_delta <= -pnl_thr:
        parts.append(f"卖出盈亏差 {pnl_delta:+,.0f}")
    out.append(
        (
            "禁止亏损周降低卖出门槛",
            f"卖出阈值 what-if：{'，'.join(parts)}，不宜降低 macro_veto / aggressive_entry",
            "sell_threshold_whatif",
        )
    )
    return out


def _candidates_from_forecast_calibrate_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not _weekly_loss(report):
        return out
    fc = report.get("forecast_calibrate_whatif") or {}
    if fc.get("skipped"):
        return out
    div_days = int(fc.get("divergence_symbol_days") or 0)
    if div_days >= int(cfg.get("forecast_divergence_days_min", 3)):
        out.append(
            (
                "禁止放宽MSS预测区间",
                f"forecast what-if：Kronos/MSS 分歧 {div_days} symbol-days，亏损周不宜放宽 base_spread",
                "forecast_calibrate_whatif",
            )
        )
    return out


def _candidates_from_optimizer_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not _weekly_loss(report):
        return out
    opt = report.get("optimizer_whatif") or {}
    if opt.get("skipped") or not opt.get("runtime_underperforms"):
        return out
    delta = float(opt.get("score_delta") or 0)
    if delta < float(cfg.get("optimizer_score_delta_min", 0.05)):
        return out
    cur = opt.get("current_params") or {}
    best = opt.get("best_params") or {}
    objective = str(opt.get("objective") or "sharpe")
    out.append(
        (
            "禁止忽视网格回测优参",
            (
                f"grid what-if（{objective}）：当前 veto={cur.get('macro_veto')} "
                f"entry={cur.get('aggressive_entry')} 落后网格最优 "
                f"veto={best.get('macro_veto')} entry={best.get('aggressive_entry')} "
                f"（Δ{delta:.3f}）"
            ),
            "optimizer_whatif",
        )
    )
    return out


def _candidates_from_kronos_whatif(
    report: dict[str, Any],
    cfg: dict[str, Any],
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if not _weekly_loss(report):
        return out
    kronos = report.get("kronos_whatif") or {}
    if kronos.get("skipped"):
        return out
    blocked = int(kronos.get("kronos_blocked_signals") or 0)
    if blocked >= int(cfg.get("kronos_blocked_signals_min", 2)):
        out.append(
            (
                "禁止无视Kronos放宽买入",
                f"Kronos what-if：本周 {blocked} 次 Kronos 阻断买入，亏损后不宜无视预警",
                "kronos_whatif",
            )
        )
    return out


def _candidates_from_macro(
    report: dict[str, Any],
    cfg: dict[str, Any],
    *,
    has_whatif_signal: bool,
) -> list[tuple[str, str, str]]:
    if not _weekly_loss(report):
        return []
    if cfg.get("require_whatif_for_macro", True) and not has_whatif_signal:
        return []
    macro = report.get("macro_signals") or {}
    verdict = str(macro.get("verdict") or macro.get("macro_verdict") or "")
    if "回避" not in verdict and not macro.get("macro_veto"):
        return []
    return [
        (
            "禁止接飞刀追涨",
            "宏观回避期逆势加仓已证伪",
            "macro",
        )
    ]


def _dedupe_candidate_triples(candidates: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    merged: dict[str, tuple[str, list[str]]] = {}
    order: list[str] = []
    for title, reason, _source in candidates:
        key = _normalize_title(title)
        if not key:
            continue
        reason = reason.strip()
        if key not in merged:
            merged[key] = (title.strip(), [])
            order.append(key)
        if reason and reason not in merged[key][1]:
            merged[key][1].append(reason)
    return [(merged[k][0], "；".join(merged[k][1])) for k in order]


def _candidates_from_weekly_report(
    report: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> list[tuple[str, str]]:
    cfg = _rejected_cfg(settings)
    tagged: list[tuple[str, str, str]] = []
    tagged.extend(_candidates_from_buy_whatif(report, cfg))
    tagged.extend(_candidates_from_sell_whatif(report, cfg))
    tagged.extend(_candidates_from_deep_loss_whatif(report, cfg))
    tagged.extend(_candidates_from_sell_threshold_whatif(report, cfg))
    tagged.extend(_candidates_from_intraday_friction_whatif(report, cfg))
    tagged.extend(_candidates_from_intraday_sell_whatif(report, cfg))
    tagged.extend(_candidates_from_forecast_calibrate_whatif(report, cfg))
    tagged.extend(_candidates_from_optimizer_whatif(report, cfg))
    tagged.extend(_candidates_from_kronos_whatif(report, cfg))
    has_whatif = any(src != "macro" for _, _, src in tagged)
    tagged.extend(_candidates_from_macro(report, cfg, has_whatif_signal=has_whatif))
    return _dedupe_candidate_triples(tagged)


def add_rejected_strategy(
    title: str,
    reason: str,
    *,
    week_start: str = "",
    week_end: str = "",
    source: str = "weekly",
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.weekly_report import trading_week_range

    if not week_start or not week_end:
        monday, friday = trading_week_range()
        week_start = week_start or monday.isoformat()
        week_end = week_end or friday.isoformat()

    existing = load_rejected_records(settings=settings)
    dup = _find_same_week_title(title, week_start=week_start, week_end=week_end, rows=existing)
    if dup:
        return dup

    record = {
        "id": _next_id(existing),
        "title": str(title).strip(),
        "reason": str(reason).strip(),
        "week_start": week_start,
        "week_end": week_end,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REJECTED_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    try:
        from agent_reach.daily_run.storage.hooks import on_rejected_strategy

        on_rejected_strategy(record, source_path=str(_REJECTED_PATH))
    except Exception:
        pass

    try:
        from agent_reach.daily_run.rejected_strategies_harness import apply_rejected_strategies_harness_refinement
        from agent_reach.daily_run.settings import load_settings

        apply_rejected_strategies_harness_refinement(
            title=str(title).strip(),
            reason=str(reason).strip(),
            source=source,
            settings=settings or load_settings(),
        )
    except Exception:
        pass

    return record


def refresh_rejected_strategies_for_week(
    report: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Saturday weekly refresh: archive expired rows, rewrite active file for next week."""
    cfg = _rejected_cfg(settings)
    if cfg.get("weekly_refresh", True) is False:
        return {"skipped": True, "reason": "weekly_refresh disabled"}

    week_end_raw = str(report.get("week_end") or "")[:10]
    if not week_end_raw:
        return {"skipped": True, "reason": "missing week_end"}

    from agent_reach.daily_run.week_forecast import next_trading_week_range

    target_start, target_end = next_trading_week_range(_parse_iso_date(week_end_raw))
    target_start_s = target_start.isoformat()
    target_end_s = target_end.isoformat()

    all_rows = load_rejected_records(limit=500, settings=settings)
    normalized: list[dict[str, Any]] = []
    for row in all_rows:
        item = dict(row)
        ws, we = _record_week_bounds(item, target_start)
        item["week_start"] = ws
        item["week_end"] = we
        normalized.append(item)

    active_rows = [
        row
        for row in normalized
        if _record_in_week(row, target_start, target_end, as_of=target_start)
    ]
    expired_rows = [
        row
        for row in normalized
        if not _record_in_week(row, target_start, target_end, as_of=target_start)
    ]

    archived = 0
    if cfg.get("archive_expired", True):
        archived = _append_archive_rows(expired_rows)

    added_titles: list[str] = []
    if cfg.get("auto_add_from_weekly", True):
        for title, reason in _candidates_from_weekly_report(report, settings):
            dup = _find_same_week_title(
                title,
                week_start=target_start_s,
                week_end=target_end_s,
                rows=active_rows,
            )
            if dup:
                continue
            record = {
                "id": _next_id(active_rows),
                "title": title,
                "reason": reason,
                "week_start": target_start_s,
                "week_end": target_end_s,
                "source": "weekly_auto",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            active_rows.append(record)
            added_titles.append(title)
            try:
                from agent_reach.daily_run.storage.hooks import on_rejected_strategy

                on_rejected_strategy(record, source_path=str(_REJECTED_PATH))
            except Exception:
                pass

    _write_rejected_records(active_rows)

    if added_titles:
        try:
            from agent_reach.daily_run.rejected_strategies_harness import apply_rejected_strategies_harness_refinement
            from agent_reach.daily_run.settings import load_settings

            apply_rejected_strategies_harness_refinement(
                title=added_titles[0],
                reason="weekly refresh auto-add",
                blocked=added_titles[1:],
                source="weekly_auto",
                settings=settings or load_settings(),
            )
        except Exception:
            pass

    return {
        "skipped": False,
        "target_week_start": target_start_s,
        "target_week_end": target_end_s,
        "active": len(active_rows),
        "archived": archived,
        "added": added_titles,
    }


def filter_rejected_items(
    items: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop improvements/skill items whose title is in rejected library."""
    keys = rejected_title_keys(settings)
    if not keys:
        return list(items), []
    kept: list[dict[str, Any]] = []
    blocked: list[str] = []
    for item in items:
        title = str(item.get("title") or "")
        key = _normalize_title(title)
        if key and key in keys:
            blocked.append(title)
            continue
        kept.append(item)
    return kept, blocked


def render_rejected_markdown(*, limit: int = 8, settings: Optional[dict[str, Any]] = None) -> str:
    rows = load_active_rejected_records(limit=limit, settings=settings)
    if not rows:
        return ""
    lines = ["### ⛔ 已证伪策略（勿重复写回）", ""]
    for row in reversed(rows[-limit:]):
        title = row.get("title") or "?"
        reason = row.get("reason") or ""
        ws = str(row.get("week_start") or "")[:10]
        we = str(row.get("week_end") or "")[:10]
        week_label = f"（{ws}~{we}）" if ws and we else ""
        lines.append(f"- **{title}**{week_label} — {reason}")
    lines.append("")
    return "\n".join(lines)
