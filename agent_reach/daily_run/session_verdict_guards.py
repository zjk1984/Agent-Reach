# -*- coding: utf-8
"""Intraday verdict guards: pullback downgrade + watchlist drawdown alerts."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def session_verdict_guard_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.session_verdict_guard_policy import session_verdict_guard_effective_cfg

    return session_verdict_guard_effective_cfg(settings)


def watchlist_drawdown_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.session_verdict_guard_policy import watchlist_drawdown_effective_cfg

    return watchlist_drawdown_effective_cfg(settings)


def format_volume_ratio_note(
    volume_ratio: float,
    change_pct: Optional[float],
    min_vol_ratio: float,
) -> str:
    """Distinguish low-volume up (stable) vs low-volume down (liquidity risk)."""
    if change_pct is not None and change_pct > 0:
        return f"量比 {volume_ratio:.2f} 缩量上行，筹码稳定"
    if change_pct is not None and change_pct < 0:
        return f"量比 {volume_ratio:.2f} < {min_vol_ratio} 缩量回调，警惕流动性"
    return f"量比 {volume_ratio:.2f} < {min_vol_ratio}"


def _buy_verdict_labels(settings: Optional[dict[str, Any]] = None) -> set[str]:
    labels = dict((settings or {}).get("verdict_labels") or {})
    return {str(labels.get("buy", "可做")), "可做", "buy"}


def morning_buy_verdict(
    session_scans: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (verdict, scan_id) for earliest morning buy label in session."""
    buy_labels = _buy_verdict_labels(settings)
    for scan in session_scans:
        sid = str(scan.get("scan_id") or "")
        source = str(scan.get("source") or "")
        if sid not in ("S1", "S2") and source not in ("morning",):
            continue
        verdict = str(scan.get("verdict") or "")
        if verdict in buy_labels:
            return verdict, sid or None
    for scan in session_scans[:2]:
        verdict = str(scan.get("verdict") or "")
        if verdict in buy_labels:
            return verdict, str(scan.get("scan_id") or "") or None
    return None, None


def _session_mss_high(session_scans: list[dict[str, Any]]) -> Optional[float]:
    values: list[float] = []
    for scan in session_scans:
        mss = scan.get("mss_final")
        if mss is None:
            continue
        try:
            values.append(float(mss))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _watchlist_row_low_pct(row: dict[str, Any]) -> Optional[float]:
    prev = _optional_float(row.get("prev_close") or row.get("pre_close"))
    day_low = _optional_float(row.get("day_low"))
    if day_low is not None and prev and prev > 0:
        return (day_low - prev) / prev * 100.0
    return _optional_float(row.get("change_pct"))


def collect_watchlist_drawdown_alerts(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Real-time drawdown sentinel for watchlist symbols (independent of MSS)."""
    cfg = watchlist_drawdown_cfg(settings)
    if not cfg.get("enabled", True):
        return []

    alerts: list[dict[str, Any]] = []
    for row in portfolio.get("watchlist") or []:
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        if not code:
            continue
        name = str(row.get("name") or code)
        change_pct = _optional_float(row.get("change_pct"))
        low_pct = _watchlist_row_low_pct(row)
        worst = change_pct
        if low_pct is not None and (worst is None or low_pct < worst):
            worst = low_pct

        severity = None
        text = ""
        if worst is not None and worst <= cfg["red_pct"]:
            severity = "red"
            text = f"{name} 日内最深 {worst:.2f}%（收盘 {change_pct:+.2f}%）" if change_pct is not None else f"{name} 日内最深 {worst:.2f}%"
        elif worst is not None and worst <= cfg["yellow_pct"]:
            severity = "yellow"
            text = f"{name} 跌幅 {worst:.2f}% 触及观察池预警线"
        if not severity:
            continue
        alerts.append(
            {
                "code": code,
                "name": name,
                "severity": severity,
                "change_pct": change_pct,
                "intraday_low_pct": low_pct,
                "worst_pct": worst,
                "text": text,
            }
        )

    alerts.sort(key=lambda a: float(a.get("worst_pct") or 0))
    return alerts


def render_watchlist_drawdown_markdown(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    alerts = collect_watchlist_drawdown_alerts(portfolio, settings=settings)
    if not alerts:
        return ""
    lines = ["**观察池跌幅哨兵**", ""]
    for alert in alerts:
        icon = "🔴" if alert.get("severity") == "red" else "🟡"
        lines.append(f"- {icon} {alert.get('text')}")
    return "\n".join(lines)


def render_session_pullback_markdown(report: dict[str, Any]) -> str:
    meta = report.get("session_pullback_downgrade")
    if not meta:
        return ""
    morning_scan = meta.get("morning_scan") or "S?"
    morning_verdict = meta.get("morning_verdict") or "可做"
    parts = []
    if meta.get("price_pullback_pct") is not None:
        parts.append(f"价格回落 {meta['price_pullback_pct']:.1f}%")
    if meta.get("mss_pullback_pts") is not None:
        parts.append(f"MSS 回落 {meta['mss_pullback_pts']:.1f} 点")
    detail = "，".join(parts) if parts else "冲高回落"
    return (
        f"**⚠️ 冲高回落降级：** 早盘 {morning_scan} **{morning_verdict}** → 现 **观察**（{detail}）"
    )


def apply_session_pullback_verdict_downgrade(
    evaluation: dict[str, Any],
    snapshot: dict[str, Any],
    session_scans: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
    *,
    pending_scan_num: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Downgrade 可做 → 观察 when morning was bullish but session pulls back."""
    cfg = session_verdict_guard_cfg(settings)
    if not cfg.get("enabled", True):
        return None

    scan_num = pending_scan_num if pending_scan_num is not None else len(session_scans) + 1
    if scan_num < cfg["min_scan_num"]:
        return None

    morning_verdict, morning_scan = morning_buy_verdict(session_scans, settings)
    if not morning_verdict:
        return None

    report = evaluation.get("report") or {}
    verdict = evaluation.get("verdict")
    labels = dict((settings or {}).get("verdict_labels") or {})
    buy_label = str(labels.get("buy", "可做"))
    watch_label = str(labels.get("watch", "观察"))
    current_verdict = str(report.get("verdict") or "")

    code = report.get("code") or snapshot.get("code")
    price = _optional_float(snapshot.get("price"))

    from agent_reach.daily_run.profit_lock import _session_high_price

    session_high = _session_high_price(session_scans, code, current_price=price)
    price_pullback = False
    pullback_pct = 0.0
    if session_high and price and session_high > 0:
        pullback_pct = (float(session_high) - float(price)) / float(session_high) * 100.0
        price_pullback = pullback_pct >= cfg["price_pullback_pct"]

    mss_high = _session_mss_high(session_scans)
    current_mss = _optional_float(report.get("mss_final"))
    mss_pullback = False
    mss_drop = 0.0
    if mss_high is not None and current_mss is not None:
        mss_drop = mss_high - current_mss
        mss_pullback = mss_drop >= cfg["mss_pullback_pts"]

    if not price_pullback and not mss_pullback:
        return None

    reason_parts: list[str] = []
    if price_pullback:
        reason_parts.append(f"自日内高点回落 {pullback_pct:.1f}%")
    if mss_pullback and mss_high is not None:
        reason_parts.append(f"MSS 自高点 {mss_high:.0f} 回落 {mss_drop:.1f} 点")
    downgrade_reason = (
        f"早盘 {morning_scan} {morning_verdict} → 冲高回落降级观察（{'，'.join(reason_parts)}）"
    )

    meta = {
        "morning_scan": morning_scan,
        "morning_verdict": morning_verdict,
        "price_pullback_pct": round(pullback_pct, 2) if price_pullback else None,
        "mss_pullback_pts": round(mss_drop, 2) if mss_pullback else None,
    }

    if current_verdict == buy_label and verdict is not None:
        report["verdict"] = watch_label
        report["confidence"] = "中"
        report.setdefault("downgrade_reasons", [])
        if downgrade_reason not in report["downgrade_reasons"]:
            report["downgrade_reasons"].append(downgrade_reason)
        verdict.label_key = "watch"
        verdict.verdict = watch_label
        verdict.confidence = "中"
        if downgrade_reason not in (verdict.downgrade_reasons or []):
            verdict.downgrade_reasons = list(verdict.downgrade_reasons or []) + [downgrade_reason]
        verdict.reasoning = f"{verdict.reasoning}；{downgrade_reason}"
        report["reasoning"] = verdict.reasoning
    else:
        report.setdefault("downgrade_reasons", [])
        if downgrade_reason not in report["downgrade_reasons"]:
            report["downgrade_reasons"].append(downgrade_reason)

    report["session_pullback_downgrade"] = meta
    return meta
