# -*- coding: utf-8
"""Market review emotion findings → harness self-evolution."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement
from agent_reach.daily_run.market_breadth_collector import emotion_conclusion_supported
from agent_reach.daily_run.market_emotion_policy import format_market_emotion_policy_line


def market_review_to_harness_evidence(
    review: Optional[dict[str, Any]],
    *,
    portfolio_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    review = review or {}
    emotion = dict(review.get("emotion") or {})
    warnings = list(review.get("warnings") or []) + list(emotion.get("warnings") or [])

    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []

    supported = emotion_conclusion_supported(emotion)
    rating = str(emotion.get("rating") or "—")
    score = emotion.get("score")
    position = str(emotion.get("position") or "—")

    if not supported:
        memory.append("市场宽度不足：收盘情绪未给出仓位建议")
        playbook.append("market_emotion：无 up/down 宽度时须 insufficient_data，禁止默认「中·5成」")
        plan.append("收盘卡检查 eastmoney/akshare/xueqiu/涨跌停池回退链路")
    else:
        basis = str(emotion.get("data_basis") or "").strip()
        if basis:
            memory.append(f"市场宽度情绪 {rating}/{score} · {position} · 依据 {basis}")
        else:
            memory.append(f"市场宽度情绪 {rating}/{score} · 建议仓位 {position}")

    fail_count = sum(
        1
        for w in warnings
        if any(k in str(w).lower() for k in ("remote", "blocked", "timeout", "失败", "不可用", "disconnected"))
    )
    if fail_count >= 3 and supported:
        playbook.append("多源降级成功仍给出仓位建议：须在卡片标明 data_basis，避免与失败警告混淆")
    if emotion.get("breadth_partial"):
        playbook.append("雪球宽度回退：涨跌停须 akshare_limit_pools 或 clist 补全后再评炸板率")

    pnl = dict(portfolio_summary or {})
    day_pnl_pct = pnl.get("day_pnl_pct")
    try:
        day_pnl = float(day_pnl_pct) if day_pnl_pct is not None else None
    except (TypeError, ValueError):
        day_pnl = None
    if supported and day_pnl is not None:
        if day_pnl <= -1.5 and rating in {"强", "中"} and str(position).startswith(("5", "7", "8")):
            memory.append(f"情绪偏多({rating}/{position})但当日组合 {day_pnl:+.2f}%")
            policy.append(
                format_market_emotion_policy_line(
                    {
                        "ratio_strong": 2.2,
                        "ratio_neutral": 1.15,
                        "limit_up_hot": 85.0,
                        "score_strong_min": 5.0,
                        "score_neutral_min": 2.0,
                    },
                    rationale="组合回撤日抬高情绪门槛",
                )
            )
        elif day_pnl >= 1.5 and rating == "弱":
            memory.append(f"情绪偏空({rating})但当日组合 {day_pnl:+.2f}%")
            playbook.append("market_emotion：弱势评级与组合盈利背离时复核 limit_up/涨跌比阈值")

    if review.get("error"):
        memory.append(f"market_review error：{review.get('error')}")
        plan.append("修复 market_review 采集后再依赖情绪定级")

    summary = (
        f"market_emotion supported={supported} rating={rating} score={score} "
        f"warnings={len(warnings)} fail_like={fail_count}"
    )
    verification_signals: list[str] = []
    if not supported:
        verification_signals.append("market_emotion_insufficient")
    if fail_count >= 3:
        verification_signals.append(f"market_review_warn={fail_count}")

    return {
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "summary": summary,
        "emotion_supported": supported,
        "emotion_rating": rating,
        "emotion_score": score,
        "verification_signals": verification_signals,
    }


def apply_market_emotion_harness_refinement(
    review: Optional[dict[str, Any]],
    *,
    portfolio_summary: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    evidence = market_review_to_harness_evidence(review, portfolio_summary=portfolio_summary)
    return apply_skill_refinement(
        "market_emotion",
        evidence,
        settings=settings,
        enabled_flag="market_review",
    )
