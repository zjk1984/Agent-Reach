# -*- coding: utf-8
"""Midday card content scope — compact market brief, macro impact, stock-only risks."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

MIDDAY_PLAN_UNCHANGED = "维持早盘计划"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holding_change_pct(holding: dict[str, Any]) -> Optional[float]:
    prev = _optional_float(holding.get("prev_close") or holding.get("pre_close"))
    price = _optional_float(holding.get("price") or holding.get("open"))
    if prev is None or prev <= 0 or price is None:
        return None
    return round((price - prev) / prev * 100.0, 2)


def _resolve_indices(enriched: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = enriched.get("sources") or {}
    quote = sources.get("quote")
    if isinstance(quote, dict) and quote.get("indices"):
        raw = quote.get("indices")
        if isinstance(raw, dict):
            return raw
    cached = enriched.get("indices")
    if isinstance(cached, dict):
        return cached
    try:
        from agent_reach.daily_run.eastmoney_market import fetch_indices

        return fetch_indices(timeout=8.0)
    except Exception:
        return {}


def build_am_market_key_points(
    enriched: dict[str, Any],
    *,
    portfolio: Optional[dict[str, Any]] = None,
    limit: int = 5,
) -> list[str]:
    """3-5 comma-ready AM market stats (indices, volume, leading theme)."""
    pf = portfolio or enriched.get("portfolio") or {}
    signals = enriched.get("macro_signals") or {}
    indices = _resolve_indices(enriched)
    points: list[str] = []

    sh_pct = _optional_float(signals.get("index_change_pct"))
    if sh_pct is None:
        sh_pct = _optional_float((indices.get("sh000001") or {}).get("change_pct"))
    if sh_pct is not None:
        points.append(f"上证 {sh_pct:+.1f}%")

    cyb_pct = _optional_float((indices.get("sz399006") or {}).get("change_pct"))
    if cyb_pct is not None:
        points.append(f"创业板 {cyb_pct:+.1f}%")

    sh_amt = _optional_float((indices.get("sh000001") or {}).get("amount"))
    sz_amt = _optional_float((indices.get("sz399001") or {}).get("amount"))
    if sh_amt is not None and sz_amt is not None and (sh_amt + sz_amt) > 0:
        total_yi = (sh_amt + sz_amt) / 1e8
        if total_yi >= 100:
            points.append(f"成交额 {total_yi:.0f}亿")
        else:
            points.append(f"成交额 {total_yi:.1f}亿")

    flow = _optional_float(signals.get("northbound_flow_yi"))
    if flow is not None and abs(flow) >= 5:
        points.append(f"北向 {flow:+.0f}亿")

    leader = _leading_theme_label(enriched, pf, indices)
    if leader:
        points.append(leader)

    if len(points) < 3:
        avg = _portfolio_avg_change(pf)
        if avg is not None:
            points.append(f"持仓均 {avg:+.1f}%")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in points:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:limit]


def _portfolio_avg_change(portfolio: dict[str, Any]) -> Optional[float]:
    vals: list[float] = []
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        pct = _holding_change_pct(row)
        if pct is not None:
            vals.append(pct)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _leading_theme_label(
    enriched: dict[str, Any],
    portfolio: dict[str, Any],
    indices: dict[str, dict[str, Any]],
) -> Optional[str]:
    best_sector = ""
    best_pct: Optional[float] = None
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        pct = _holding_change_pct(row)
        if pct is None:
            continue
        label = str(row.get("sector") or row.get("industry") or "").strip()
        if not label:
            continue
        if best_pct is None or pct > best_pct:
            best_pct = pct
            best_sector = label
    if best_sector and best_pct is not None and best_pct >= 0.8:
        return f"{best_sector}板块领涨"

    try:
        from agent_reach.daily_run.market_review import load_market_review
        from agent_reach.daily_run.trade_calendar import today_shanghai

        review = load_market_review(today_shanghai().isoformat())
        mainline = str((review or {}).get("dominant_mainline") or "").strip()
        if mainline and mainline not in {"—", "-"}:
            return f"{mainline}主线活跃"
    except Exception:
        pass

    hot = (enriched.get("macro_signals") or {}).get("portfolio_hot_stocks") or []
    if hot:
        name = str(hot[0].get("name") or hot[0].get("keyword") or "").strip()
        if name:
            return f"{name[:8]}舆情活跃"
    return None


def build_macro_holdings_impact_line(
    enriched: dict[str, Any],
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """One sentence: macro view + impact on holdings."""
    pf = portfolio or enriched.get("portfolio") or {}
    signals = enriched.get("macro_signals") or {}
    sources = enriched.get("sources") or {}

    try:
        from agent_reach.daily_run.morning_content_scope import (
            infer_affected_sectors,
            infer_impact_label,
            select_macro_headlines,
        )

        featured, _extra = select_macro_headlines(
            macro_signals=signals,
            sources=sources,
            portfolio=pf,
            limit=1,
        )
        if featured:
            title = str(featured[0].get("title") or "").strip()[:48]
            sectors = infer_affected_sectors(title, pf) or "持仓板块"
            impact = infer_impact_label(title)
            if impact == "利好":
                effect = f"{sectors}受益"
            elif impact == "利空":
                effect = f"{sectors}承压"
            else:
                effect = f"{sectors}波动有限"
            return f"宏观：{title}，对持仓影响：{effect}"
    except Exception:
        pass

    idx = _optional_float(signals.get("index_change_pct"))
    if idx is None:
        indices = _resolve_indices(enriched)
        idx = _optional_float((indices.get("sh000001") or {}).get("change_pct"))
    if idx is not None:
        if idx >= 0.8:
            return "宏观：大盘偏强，对持仓影响：整体风险偏好抬升"
        if idx <= -0.8:
            return "宏观：大盘偏弱，对持仓影响：宜控制仓位、优先防守"
        return "宏观：大盘震荡，对持仓影响：以个股计划为主"

    avg = _portfolio_avg_change(pf)
    if avg is not None:
        if avg >= 1.0:
            return "宏观：持仓整体偏强，对持仓影响：可按计划执行"
        if avg <= -1.0:
            return "宏观：持仓整体走弱，对持仓影响：优先风控"
    return ""


def build_morning_reference_line(
    morning_handoff: Optional[dict[str, Any]],
    *,
    close_handoff: Optional[dict[str, Any]] = None,
) -> str:
    """Brief '早盘提到 XXX' when a prior judgment still matters."""
    for action in (morning_handoff or {}).get("action_checklist") or []:
        if not isinstance(action, dict):
            continue
        trigger = str(action.get("trigger") or "").strip()
        operation = str(action.get("operation") or "").strip()
        if trigger and trigger not in {"—", "-"}:
            name = str(action.get("name") or action.get("code") or "").strip()
            snippet = f"{name}{operation}{trigger}" if name else f"{operation}{trigger}"
            return f"早盘提到 {snippet[:56]}"
        reasoning = str(action.get("reasoning") or action.get("note") or "").strip()
        if reasoning:
            return f"早盘提到 {reasoning[:56]}"

    for item in (close_handoff or {}).get("tomorrow_focus") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            return f"早盘提到 {text[:56]}"
    return ""


def build_holding_risk_lines(
    *,
    portfolio: dict[str, Any],
    enriched: dict[str, Any],
    evaluation: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    limit: int = 5,
) -> list[str]:
    """Stock-specific afternoon risks for current holdings only."""
    from agent_reach.daily_run.close_morning_handoff import (
        _assess_risk_status,
        load_close_handoff_for_morning,
    )

    holding_codes = {
        _normalize_code(str(row.get("code") or ""))
        for row in (portfolio.get("holdings") or [])
        if isinstance(row, dict) and row.get("code")
    }
    if not holding_codes:
        return []

    close_handoff = load_close_handoff_for_morning(settings=settings)
    report = (evaluation or {}).get("report") or {}
    lines: list[str] = []

    for item in (close_handoff or {}).get("watch_risks") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(str(item.get("code") or ""))
        if code and code not in holding_codes:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        name = str(item.get("name") or code or "—")
        holding = _find_holding(portfolio, code, name)
        status, detail = _assess_risk_status(text, holding, enriched, report)
        if status == "仍待观察" and detail in {"数据不足", "—"}:
            continue
        lines.append(f"- **{name}** {detail}（{status}）")
        if len(lines) >= limit:
            break
    return lines


def _find_holding(portfolio: dict[str, Any], code: str, name: str) -> dict[str, Any]:
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        if code and _normalize_code(str(row.get("code") or "")) == code:
            return dict(row)
        if name and str(row.get("name") or "") == name:
            return dict(row)
    return {}


def compact_afternoon_display(row: dict[str, Any]) -> str:
    if row.get("data_stale"):
        return "⚠️ 待行情更新"
    if not row.get("changed"):
        return MIDDAY_PLAN_UNCHANGED
    action = str(row.get("afternoon_action") or MIDDAY_PLAN_UNCHANGED).strip()
    for prefix in (
        "截至 11:30 收盘 · ",
        "上午实际走势超预期，调整下午预测 · ",
    ):
        if action.startswith(prefix):
            action = action[len(prefix) :]
    return action or MIDDAY_PLAN_UNCHANGED
