# -*- coding: utf-8
"""Market breadth and emotion scoring (a-stock-review-skill)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MarketEmotion:
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    limit_up: int = 0
    limit_down: int = 0
    broken_count: int = 0
    broken_rate: float = 0.0
    ratio: str = "0:0"
    ratio_num: float = 0.0
    score: int = 0
    rating: str = "中"
    position: str = "5成"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    northbound_net_yi: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "up_count": self.up_count,
            "down_count": self.down_count,
            "flat_count": self.flat_count,
            "limit_up": self.limit_up,
            "limit_down": self.limit_down,
            "broken_count": self.broken_count,
            "broken_rate": round(self.broken_rate, 4),
            "ratio": self.ratio,
            "ratio_num": round(self.ratio_num, 3),
            "score": self.score,
            "rating": self.rating,
            "position": self.position,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "northbound_net_yi": self.northbound_net_yi,
        }


def analyze_emotion(
    stocks: list[dict[str, Any]],
    north: dict[str, Any],
    *,
    indices: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> MarketEmotion:
    """Score market emotion from full A-share snapshot (upstream analyzeEmotion)."""
    _ = indices  # reserved for future index-weighted scoring
    up_count = sum(1 for s in stocks if _pct(s) > 0)
    down_count = sum(1 for s in stocks if _pct(s) < 0)
    flat_count = sum(1 for s in stocks if _pct(s) == 0)
    limit_up = sum(1 for s in stocks if _pct(s) >= 9.8)
    limit_down = sum(1 for s in stocks if _pct(s) <= -9.8)
    near_limit = sum(1 for s in stocks if 8 <= _pct(s) < 9.8)
    return _score_market_emotion(
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        limit_up=limit_up,
        limit_down=limit_down,
        near_limit=near_limit,
        north=north,
        include_limit_scoring=True,
        include_breadth_scoring=True,
        settings=settings,
    )


def enrich_emotion_with_limit_pools(
    emotion: MarketEmotion | dict[str, Any],
    pool: dict[str, Any],
    north: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> MarketEmotion:
    """Re-score emotion after attaching akshare limit pool stats."""
    if isinstance(emotion, dict):
        up_count = int(emotion.get("up_count") or 0)
        down_count = int(emotion.get("down_count") or 0)
        flat_count = int(emotion.get("flat_count") or 0)
        prior_warnings = list(emotion.get("warnings") or [])
        prior_reasons = list(emotion.get("reasons") or [])
    else:
        up_count = emotion.up_count
        down_count = emotion.down_count
        flat_count = emotion.flat_count
        prior_warnings = list(emotion.warnings)
        prior_reasons = list(emotion.reasons)

    limit_up = int(pool.get("limit_up") or 0)
    limit_down = int(pool.get("limit_down") or 0)
    broken_count = int(pool.get("broken_count") or 0)
    include_breadth = up_count + down_count > 0

    em = _score_market_emotion(
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        limit_up=limit_up,
        limit_down=limit_down,
        near_limit=broken_count,
        north=north,
        include_limit_scoring=True,
        include_breadth_scoring=include_breadth,
        settings=settings,
    )
    limit_keywords = ("涨停", "跌停", "炸板率")
    if not include_breadth:
        limit_reasons = [r for r in em.reasons if any(k in r for k in limit_keywords)]
        em.reasons = prior_reasons + limit_reasons
    else:
        prefix = [r for r in prior_reasons if "雪球宽度" in r]
        em.reasons = prefix + [r for r in em.reasons if r not in prefix]

    em.warnings = [
        w
        for w in prior_warnings
        if "涨跌停/炸板率需 Eastmoney clist" not in w
    ]
    source = str(pool.get("source") or "akshare_limit_pools")
    em.warnings.append(f"涨跌停来自 {source} 回退（非 clist 全市场扫描）")
    return em


def analyze_emotion_from_counts(
    up_count: int,
    down_count: int,
    flat_count: int,
    north: dict[str, Any],
    *,
    indices: Optional[dict[str, Any]] = None,
    by_market: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> MarketEmotion:
    """Score emotion from aggregate rise/fall/flat (Xueqiu index detail fallback)."""
    _ = indices
    em = _score_market_emotion(
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        limit_up=0,
        limit_down=0,
        near_limit=0,
        north=north,
        include_limit_scoring=False,
        include_breadth_scoring=True,
        settings=settings,
    )
    em.warnings.append("涨跌停/炸板率需 Eastmoney clist，当前为雪球宽度回退")
    if by_market:
        parts = []
        for label, row in by_market.items():
            if isinstance(row, dict):
                parts.append(
                    f"{label} {row.get('rise_count', 0)}:{row.get('fall_count', 0)}"
                )
        if parts:
            em.reasons.insert(0, f"雪球宽度（{' · '.join(parts)}）")
    else:
        em.reasons.insert(0, "雪球宽度（沪+深涨跌平汇总）")
    return em


def _score_market_emotion(
    *,
    up_count: int,
    down_count: int,
    flat_count: int,
    limit_up: int,
    limit_down: int,
    near_limit: int,
    north: dict[str, Any],
    include_limit_scoring: bool,
    include_breadth_scoring: bool = True,
    settings: Optional[dict[str, Any]] = None,
) -> MarketEmotion:
    from agent_reach.daily_run.market_emotion_policy import (
        market_emotion_policy_default,
        rating_position_from_score,
    )

    broken_rate = near_limit / (limit_up + near_limit) if (limit_up + near_limit) > 0 else 0.0

    ratio_strong = float(market_emotion_policy_default(settings, "ratio_strong"))
    ratio_neutral = float(market_emotion_policy_default(settings, "ratio_neutral"))
    limit_up_hot = int(round(market_emotion_policy_default(settings, "limit_up_hot")))
    limit_up_normal = int(round(market_emotion_policy_default(settings, "limit_up_normal")))
    limit_down_panic = int(round(market_emotion_policy_default(settings, "limit_down_panic")))
    limit_down_local = int(round(market_emotion_policy_default(settings, "limit_down_local")))
    broken_rate_weak = float(market_emotion_policy_default(settings, "broken_rate_weak"))
    broken_rate_moderate = float(market_emotion_policy_default(settings, "broken_rate_moderate"))
    north_inflow_strong = float(market_emotion_policy_default(settings, "north_inflow_strong"))
    north_outflow_strong = float(market_emotion_policy_default(settings, "north_outflow_strong"))

    score = 0
    reasons: list[str] = []
    warnings: list[str] = []
    ratio_num = up_count / down_count if down_count > 0 else float(up_count)

    if include_breadth_scoring:
        if ratio_num > ratio_strong:
            score += 3
            reasons.append(f"涨跌比 {up_count}:{down_count}，赚钱效应强")
        elif ratio_num > ratio_neutral:
            score += 1
            reasons.append(f"涨跌比 {up_count}:{down_count}，偏中性")
        else:
            score -= 2
            reasons.append(f"涨跌比 {up_count}:{down_count}，亏钱效应明显")

    if include_limit_scoring:
        if limit_up >= limit_up_hot:
            score += 2
            reasons.append(f"涨停 {limit_up} 家，情绪火爆")
        elif limit_up >= limit_up_normal:
            score += 1
            reasons.append(f"涨停 {limit_up} 家，情绪正常")
        else:
            reasons.append(f"涨停仅 {limit_up} 家")

        if limit_down >= limit_down_panic:
            score -= 2
            warnings.append(f"跌停 {limit_down} 家，恐慌蔓延")
            reasons.append(f"跌停 {limit_down} 家")
        elif limit_down >= limit_down_local:
            score -= 1
            reasons.append(f"跌停 {limit_down} 家，局部恐慌")
        else:
            reasons.append(f"跌停 {limit_down} 家")

        if broken_rate > broken_rate_weak:
            score -= 2
            reasons.append(f"炸板率 {broken_rate * 100:.0f}%，追高意愿弱")
        elif broken_rate > broken_rate_moderate:
            score -= 1
            reasons.append(f"炸板率 {broken_rate * 100:.0f}%，封板一般")

    net_raw = north.get("net_yi")
    northbound_net_yi: Optional[float] = None
    if north.get("disclosure_limited"):
        reasons.append("北向净买额未披露（东财停实时披露）")
    elif north.get("available") is False or net_raw is None:
        reasons.append("北向数据不可用")
    else:
        net = float(net_raw)
        northbound_net_yi = net
        if net > north_inflow_strong:
            score += 1
            reasons.append(f"北向大幅流入 {net:.0f} 亿")
        elif net > 0:
            reasons.append(f"北向小幅流入 {net:.0f} 亿")
        elif net < -north_outflow_strong:
            score -= 1
            warnings.append(f"北向大幅流出 {abs(net):.0f} 亿")
            reasons.append(f"北向大幅流出 {abs(net):.0f} 亿")
        elif net < 0:
            reasons.append(f"北向小幅流出 {abs(net):.0f} 亿")

    rating, position = rating_position_from_score(score, settings=settings)

    return MarketEmotion(
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        limit_up=limit_up,
        limit_down=limit_down,
        broken_count=near_limit,
        broken_rate=broken_rate,
        ratio=f"{up_count}:{down_count}",
        ratio_num=ratio_num,
        score=score,
        rating=rating,
        position=position,
        reasons=reasons,
        warnings=warnings,
        northbound_net_yi=northbound_net_yi,
    )


def collect_market_breadth(
    stocks: list[dict[str, Any]],
    north: dict[str, Any],
    *,
    indices: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> MarketEmotion:
    return analyze_emotion(stocks, north, indices=indices, settings=settings)


def emotion_conclusion_supported(emotion: Optional[dict[str, Any]]) -> bool:
    """Whether score/rating/position are backed by rise/fall breadth (not index-only guess)."""
    if not emotion:
        return False
    if emotion.get("insufficient_data") is True:
        return False
    up = int(emotion.get("up_count") or 0)
    down = int(emotion.get("down_count") or 0)
    return up + down > 0


def emotion_data_basis(emotion: dict[str, Any]) -> str:
    """Human-readable provenance for partial/degraded market-review inputs."""
    parts: list[str] = []
    if int(emotion.get("up_count") or 0) + int(emotion.get("down_count") or 0) > 0:
        if emotion.get("breadth_source") == "xueqiu" or emotion.get("breadth_partial"):
            parts.append("雪球沪深宽度")
        elif emotion.get("breadth_degraded"):
            parts.append("涨跌家数（降级）")
        else:
            parts.append("全A涨跌家数")
    limit_src = str(emotion.get("limit_source") or "").strip()
    if limit_src:
        parts.append(f"涨跌停池({limit_src})")
    elif int(emotion.get("limit_up") or 0) + int(emotion.get("limit_down") or 0) > 0:
        parts.append("涨跌停统计")
    return " + ".join(parts)


def mark_emotion_data_quality(emotion: dict[str, Any]) -> dict[str, Any]:
    """Attach insufficient_data / data_basis flags for close-card rendering."""
    out = dict(emotion)
    out["insufficient_data"] = (
        int(out.get("up_count") or 0) + int(out.get("down_count") or 0) <= 0
    )
    basis = emotion_data_basis(out)
    if basis:
        out["data_basis"] = basis
    return out


def _pct(stock: dict[str, Any]) -> float:
    try:
        return float(stock.get("change_pct") or 0)
    except (TypeError, ValueError):
        return 0.0
