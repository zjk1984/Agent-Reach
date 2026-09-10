# -*- coding: utf-8
"""Systemic risk detectors: emotion cooling, tech concentration, benchmark streak."""

from __future__ import annotations

from typing import Any, Optional

from datetime import date

from agent_reach.daily_run.snapshot_builder import _normalize_code

_TECH_CLUSTER_TOKENS: tuple[str, ...] = (
    "半导体",
    "存储",
    "AI算力",
    "光通信",
    "面板",
    "消费电子",
    "电子",
    "芯片",
    "封装",
    "算力",
    "显示",
    "光学",
)

_SYSTEMIC_NEUTRAL: dict[str, Any] = {
    "enabled": True,
    "tech_cluster_ratio_warn": 0.70,
    "tech_cluster_ratio_block_buy": 0.70,
    "tech_cluster_score_penalty": 2.0,
    "non_tech_score_boost": 2.0,
    "diversify_watchlist_enabled": True,
    "emotion_cooling_limit_up_delta": -15,
    "emotion_cooling_limit_down_delta": 3,
    "emotion_cooling_macro_veto_bump": 2.0,
    "block_tech_buy_on_cooling": True,
    "benchmark_underperform_threshold_pct": -0.20,
    "benchmark_streak_warn_days": 2,
    "benchmark_streak_defensive_days": 3,
}


def systemic_risk_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("systemic_risk") or {})
    out = {**_SYSTEMIC_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", True))
    return out


def format_northbound_display(
    north: Optional[dict[str, Any]] = None,
    *,
    emotion: Optional[dict[str, Any]] = None,
) -> str:
    """Human label for northbound — distinguish undisclosed vs missing vs numeric."""
    north = north or {}
    if north.get("disclosure_limited"):
        return "净买额未披露（东财停实时披露）"
    if north.get("available") is False or north.get("net_yi") is None:
        em_val = (emotion or {}).get("northbound_net_yi")
        if em_val is None:
            return "不可用"
    net_yi = north.get("net_yi")
    if net_yi is None:
        net_yi = (emotion or {}).get("northbound_net_yi")
    if net_yi is None:
        return "不可用"
    return f"{float(net_yi):+.2f} 亿"


def is_tech_cluster_sector(label: Any) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    return any(token in text for token in _TECH_CLUSTER_TOKENS)


def _row_sector(row: dict[str, Any]) -> str:
    return str(row.get("sector") or row.get("industry") or "").strip()


def tech_concentration_snapshot(
    portfolio: dict[str, Any],
    watchlist: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Tech-cluster share across holdings + watchlist-only symbols."""
    held_codes = {
        _normalize_code(str(h.get("code") or ""))
        for h in (portfolio.get("holdings") or [])
        if int(h.get("shares") or 0) > 0
    }
    symbols: list[dict[str, Any]] = list(portfolio.get("holdings") or [])
    for row in watchlist or portfolio.get("watchlist") or []:
        code = _normalize_code(str(row.get("code") or ""))
        if code and code not in held_codes:
            symbols.append(row)

    total = len(symbols)
    if total <= 0:
        return {"ratio": 0.0, "tech_count": 0, "total": 0, "tech_names": []}

    tech_rows = [s for s in symbols if is_tech_cluster_sector(_row_sector(s))]
    ratio = len(tech_rows) / total
    names = [
        str(s.get("name") or s.get("code") or "?")
        for s in tech_rows[:5]
    ]
    return {
        "ratio": ratio,
        "tech_count": len(tech_rows),
        "total": total,
        "tech_names": names,
    }


def watchlist_diversify_score_adjustment(
    row: dict[str, Any],
    *,
    portfolio: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> float:
    cfg = systemic_risk_cfg(settings)
    if not cfg.get("diversify_watchlist_enabled", True):
        return 0.0
    snap = tech_concentration_snapshot(portfolio)
    if float(snap.get("ratio") or 0) < float(cfg.get("tech_cluster_ratio_warn", 0.7)):
        return 0.0
    if is_tech_cluster_sector(_row_sector(row)):
        return -float(cfg.get("tech_cluster_score_penalty", 2.0))
    return float(cfg.get("non_tech_score_boost", 2.0))


def _market_review_from_snapshot(snapshot: dict[str, Any]) -> Optional[dict[str, Any]]:
    review = snapshot.get("market_review")
    if not isinstance(review, dict):
        return None
    if review.get("date") or review.get("comparison") or review.get("emotion") or review.get("sector_analysis"):
        return review
    return None


def detect_emotion_cooling(
    market_review: Optional[dict[str, Any]] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return cooling context when limit-up fades and mainline is scattered."""
    if not market_review:
        return None
    cfg = systemic_risk_cfg(settings)
    emotion = market_review.get("emotion") or {}
    comparison = market_review.get("comparison") or {}
    vs_y = comparison.get("vs_yesterday") or {}
    sector = market_review.get("sector_analysis") or {}

    limit_up_delta = vs_y.get("limit_up_delta")
    limit_down_delta = vs_y.get("limit_down_delta")
    cooling_signals: list[str] = []

    if limit_up_delta is not None and int(limit_up_delta) <= int(cfg.get("emotion_cooling_limit_up_delta", -15)):
        cooling_signals.append(f"涨停较昨日 {int(limit_up_delta):+d}")
    if limit_down_delta is not None and int(limit_down_delta) >= int(cfg.get("emotion_cooling_limit_down_delta", 3)):
        cooling_signals.append(f"跌停较昨日 {int(limit_down_delta):+d}")
    if str(sector.get("mainline_type") or "") == "多题材轮动":
        cooling_signals.append(str(sector.get("reasoning") or "题材分散"))

    north = market_review.get("north") or {}
    if north.get("disclosure_limited"):
        cooling_signals.append("北向净买额未披露")
    elif emotion.get("rating") in ("弱", "极弱"):
        cooling_signals.append(f"情绪评级 {emotion.get('rating')}")

    if not cooling_signals:
        return None
    return {
        "signals": cooling_signals,
        "limit_up_delta": limit_up_delta,
        "limit_down_delta": limit_down_delta,
        "mainline_type": sector.get("mainline_type"),
    }


def intraday_macro_veto_systemic_bump(
    base_macro_veto: float,
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[float, Optional[str]]:
    """Extra macro_veto bump when market emotion is cooling."""
    cfg = systemic_risk_cfg(settings)
    if not cfg.get("enabled", True):
        return float(base_macro_veto), None

    review = _market_review_from_snapshot(snapshot)
    if review is None:
        from agent_reach.daily_run.market_review import load_market_review
        from agent_reach.daily_run.trade_calendar import today_shanghai

        review = load_market_review(today_shanghai().isoformat())

    cooling = detect_emotion_cooling(review, settings=settings)
    if not cooling:
        return float(base_macro_veto), None

    bump = float(cfg.get("emotion_cooling_macro_veto_bump", 2.0))
    effective = min(50.0, float(base_macro_veto) + bump)
    note = f"（情绪降温 {cooling['signals'][0][:24]}… macro_veto +{bump:.0f}→{effective:.0f}）"
    return effective, note


def systemic_buy_block_reason(
    settings: dict[str, Any],
    *,
    code: str,
    snapshot: dict[str, Any],
) -> Optional[str]:
    """Block adding tech-cluster exposure when emotion is cooling and already concentrated."""
    cfg = systemic_risk_cfg(settings)
    if not cfg.get("enabled", True) or not cfg.get("block_tech_buy_on_cooling", True):
        return None

    portfolio = snapshot.get("portfolio") or {}
    conc = tech_concentration_snapshot(portfolio)
    if float(conc.get("ratio") or 0) < float(cfg.get("tech_cluster_ratio_block_buy", 0.7)):
        return None

    review = _market_review_from_snapshot(snapshot)
    if review is None:
        from agent_reach.daily_run.market_review import load_market_review
        from agent_reach.daily_run.trade_calendar import today_shanghai

        review = load_market_review(today_shanghai().isoformat())
    if not detect_emotion_cooling(review, settings=settings):
        return None

    norm = _normalize_code(code)
    sector = ""
    for h in portfolio.get("holdings") or []:
        if _normalize_code(str(h.get("code") or "")) == norm:
            sector = _row_sector(h)
            break
    for row in snapshot.get("symbols") or []:
        if _normalize_code(str(row.get("code") or "")) == norm:
            sector = _row_sector(row) or sector
            break
    if not is_tech_cluster_sector(sector):
        return None

    pct = float(conc.get("ratio") or 0) * 100
    return (
        f"系统性风险：科技链集中度 {pct:.0f}% 且市场情绪降温，"
        f"暂停同类加仓（{sector or code}）"
    )


def compute_benchmark_excess_pct(
    portfolio_pct: Optional[float],
    market_review: Optional[dict[str, Any]],
) -> Optional[float]:
    if portfolio_pct is None or not market_review:
        return None
    indices = market_review.get("indices") or {}
    hs300 = indices.get("sh000300") or {}
    bench_pct = hs300.get("change_pct")
    if bench_pct is None:
        for info in indices.values():
            if isinstance(info, dict) and info.get("change_pct") is not None:
                name = str(info.get("name") or "")
                if "300" in name or "沪深" in name:
                    bench_pct = info.get("change_pct")
                    break
    if bench_pct is None:
        return None
    return round(float(portfolio_pct) - float(bench_pct), 2)


def benchmark_underperformance_streak(
    *,
    settings: Optional[dict[str, Any]] = None,
    as_of: Optional[str] = None,
    current_portfolio_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Count consecutive days with excess return below threshold."""
    cfg = systemic_risk_cfg(settings)
    threshold = float(cfg.get("benchmark_underperform_threshold_pct", -0.20))
    warn_days = int(cfg.get("benchmark_streak_warn_days", 2))
    defensive_days = int(cfg.get("benchmark_streak_defensive_days", 3))

    from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history
    from agent_reach.daily_run.market_review import load_market_review
    from agent_reach.daily_run.prior_close import prev_trading_day
    from agent_reach.daily_run.trade_calendar import today_shanghai

    day = as_of or today_shanghai().isoformat()
    rows = load_daily_pnl_history(settings=settings)
    by_date = {r.date: r for r in rows}

    streak = 0
    details: list[dict[str, Any]] = []
    cursor_day = day
    first = True

    for _ in range(10):
        pf_pct: Optional[float]
        if first and current_portfolio_pct is not None:
            pf_pct = float(current_portfolio_pct)
            first = False
        else:
            rec = by_date.get(cursor_day)
            pf_pct = rec.daily_pnl_pct if rec else None

        review = load_market_review(cursor_day)
        excess = compute_benchmark_excess_pct(pf_pct, review)
        if excess is None:
            break
        details.append(
            {
                "date": cursor_day,
                "portfolio_pct": pf_pct,
                "excess_pct": excess,
            }
        )
        if excess >= threshold:
            break
        streak += 1
        prev = prev_trading_day(
            date.fromisoformat(cursor_day),
            settings=settings,
        )
        cursor_day = prev.isoformat()

    return {
        "streak_days": streak,
        "threshold_pct": threshold,
        "warn": streak >= warn_days,
        "defensive": streak >= defensive_days,
        "details": list(reversed(details)),
    }


def collect_systemic_risk_findings(
    *,
    current: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
    market_review: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Structured findings for close improvements / harness."""
    cfg = systemic_risk_cfg(settings)
    if not cfg.get("enabled", True):
        return []

    findings: list[dict[str, Any]] = []
    review = market_review or _market_review_from_snapshot(current)
    if review is None:
        from agent_reach.daily_run.market_review import load_market_review
        from agent_reach.daily_run.trade_calendar import today_shanghai

        review = load_market_review(today_shanghai().isoformat())

    cooling = detect_emotion_cooling(review, settings=settings)
    if cooling:
        north = (review or {}).get("north") or {}
        north_label = format_northbound_display(north, emotion=(review or {}).get("emotion"))
        findings.append(
            {
                "priority": "high",
                "title": "市场情绪降温",
                "detail": (
                    f"{'；'.join(cooling['signals'][:3])}；北向 {north_label}。"
                    "明日维持高现金，暂停追涨同类科技加仓"
                ),
            }
        )

    portfolio = current.get("portfolio") or {}
    conc = tech_concentration_snapshot(portfolio, current.get("watchlist"))
    ratio = float(conc.get("ratio") or 0)
    if ratio >= float(cfg.get("tech_cluster_ratio_warn", 0.7)):
        names = "、".join(conc.get("tech_names") or [])
        findings.append(
            {
                "priority": "high",
                "title": "科技链高度集中",
                "detail": (
                    f"持仓+观察池 {conc.get('tech_count')}/{conc.get('total')} "
                    f"({ratio:.0%}) 属科技/半导体/消费电子链（{names}）；"
                    "明日优先 rotation 至非科技候选，单链合计≤50%"
                ),
            }
        )

    pf = current.get("portfolio") or {}
    streak_info = benchmark_underperformance_streak(
        settings=settings,
        current_portfolio_pct=pf.get("daily_pnl_pct") or current.get("daily_pnl_pct"),
    )
    if streak_info.get("warn"):
        parts = []
        for row in streak_info.get("details") or []:
            parts.append(
                f"{row.get('date')} 超额 {float(row.get('excess_pct') or 0):+.2f}%"
            )
        priority = "high" if streak_info.get("defensive") else "medium"
        findings.append(
            {
                "priority": priority,
                "title": "连续跑输基准",
                "detail": (
                    f"{' · '.join(parts)}；"
                    + (
                        f"已连续 {streak_info['streak_days']} 日低于 {streak_info['threshold_pct']:+.2f}%，"
                        "评估 deploy_ratio 与 rotation"
                        if streak_info.get("defensive")
                        else "关注是否为持续性现象，暂勿过度收紧 MSS"
                    )
                ),
            }
        )

    return findings


def current_from_portfolio_summary(
    portfolio_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Minimal ``current`` payload for systemic risk detectors from close summary."""
    ps = portfolio_summary or {}
    holdings = list(ps.get("holdings") or [])
    watchlist = list(ps.get("watchlist") or [])
    return {
        "portfolio": {
            "holdings": holdings,
            "watchlist": watchlist,
            "daily_pnl_pct": ps.get("daily_pnl_pct"),
        },
        "watchlist": watchlist,
        "daily_pnl_pct": ps.get("daily_pnl_pct"),
    }


def systemic_risk_narrative_context(
    *,
    portfolio_summary: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    market_review: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    """Structured systemic-risk lines for close DeepSeek interpretation (no new numbers)."""
    findings = collect_systemic_risk_findings(
        current=current_from_portfolio_summary(portfolio_summary),
        settings=settings,
        market_review=market_review,
    )
    return [
        {
            "priority": str(item.get("priority") or ""),
            "title": str(item.get("title") or ""),
            "detail": str(item.get("detail") or ""),
        }
        for item in findings
    ]
