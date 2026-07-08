# -*- coding: utf-8 -*-
"""Verdict labels: 可做 / 观察 / 回避."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VerdictResult:
    verdict: str
    confidence: str
    mss_final: float
    entry_price: Optional[float]
    stop_loss_price: Optional[float]
    invalidation: str
    reasoning: str
    downgrade_reasons: list[str] = field(default_factory=list)
    blocked: bool = False
    label_key: str = "watch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "mss_final": self.mss_final,
            "entry_price": self.entry_price,
            "stop_loss_price": self.stop_loss_price,
            "invalidation": self.invalidation,
            "reasoning": self.reasoning,
            "downgrade_reasons": self.downgrade_reasons,
            "blocked": self.blocked,
            "label_key": self.label_key,
        }


def compute_mss(breakdown: dict[str, float], settings: dict[str, Any]) -> float:
    weights = settings.get("mss_weights", {})
    total = 0.0
    weight_sum = 0.0
    for key, weight in weights.items():
        if key in breakdown:
            total += float(breakdown[key]) * float(weight)
            weight_sum += float(weight)
    if weight_sum <= 0:
        return float(breakdown.get("total", 0))
    return round(total / weight_sum * (weight_sum if weight_sum < 1 else 1), 2)


def compute_verdict(snapshot: dict[str, Any], settings: dict[str, Any]) -> VerdictResult:
    """Compute trading label from MSS, technicals, and audit context."""
    labels = settings.get("verdict_labels", {})
    buy_label = labels.get("buy", "可做")
    watch_label = labels.get("watch", "观察")
    avoid_label = labels.get("avoid", "回避")

    thresholds = settings.get("thresholds", {})
    trading = settings.get("trading", {})

    macro_veto = float(thresholds.get("macro_veto", 40))
    aggressive = float(thresholds.get("aggressive_entry", 50))
    high_pos = float(thresholds.get("high_position_20d", 0.7))
    min_vol_ratio = float(thresholds.get("min_volume_ratio", 1.0))
    max_vwap_dev = float(thresholds.get("max_vwap_deviation_pct", 0.04))

    breakdown = snapshot.get("mss_breakdown") or {}
    mss = snapshot.get("mss_final")
    if mss is None:
        mss = compute_mss(breakdown, settings)
    mss = float(mss)

    price = _optional_float(snapshot.get("price"))
    ma20 = _optional_float(snapshot.get("ma20"))
    position_20d = _optional_float(snapshot.get("position_20d"))
    volume_ratio = _optional_float(snapshot.get("volume_ratio"))
    vwap_deviation = _optional_float(snapshot.get("vwap_deviation_pct"))

    downgrade: list[str] = []
    label_key = "watch"
    blocked = False
    confidence = "高"

    technical_complete = all(v is not None for v in (price, ma20, position_20d))

    if mss < macro_veto:
        label_key = "avoid"
        blocked = True
        reasoning = f"MSS {mss:.0f} 低于宏观一票否决线 {macro_veto:.0f}，禁止买入"
    elif not technical_complete:
        label_key = "watch"
        downgrade.append("缺少完整技术面数据（price/ma20/position_20d）")
        reasoning = f"MSS {mss:.0f}，但技术面数据不完整，仅观察"
        confidence = "中"
    elif mss < aggressive:
        label_key = "watch"
        reasoning = f"MSS {mss:.0f} 低于进攻阈值 {aggressive:.0f}，维持高现金观望"
        confidence = "中"
    else:
        label_key = "buy"
        reasoning = f"MSS {mss:.0f} 达进攻阈值，技术面共振允许条件性建仓"

    if position_20d is not None and position_20d > high_pos and mss < aggressive:
        if label_key == "buy":
            label_key = "watch"
        downgrade.append(f"20日价格位置 {position_20d:.0%} 偏高且 MSS 未达 {aggressive:.0f}")
        confidence = "中"

    if volume_ratio is None:
        if confidence == "高":
            confidence = "中"
        downgrade.append("缺少量比 volume_ratio")
    elif volume_ratio < min_vol_ratio and label_key == "buy":
        label_key = "watch"
        downgrade.append(f"量比 {volume_ratio:.2f} < {min_vol_ratio}")

    if vwap_deviation is not None and abs(vwap_deviation) >= max_vwap_dev:
        if volume_ratio is not None and volume_ratio < min_vol_ratio:
            label_key = "avoid"
            blocked = True
            downgrade.append(f"VWAP 偏离 {vwap_deviation:.1%} 且量比不足")
        elif label_key == "buy":
            label_key = "watch"
            downgrade.append(f"VWAP 偏离 {vwap_deviation:.1%} 过大")

    if snapshot.get("audit_passed") is False:
        label_key = "watch" if label_key != "avoid" else "avoid"
        blocked = True
        downgrade.append("数据审计未通过")
        confidence = "低"

    if not snapshot.get("structured_review_complete", True):
        if label_key == "buy":
            label_key = "watch"
        downgrade.append("未完成结构化复核")
        confidence = "低"

    verdict_map = {"buy": buy_label, "watch": watch_label, "avoid": avoid_label}
    verdict = verdict_map[label_key]

    stop_loss = None
    entry = price
    if price is not None and ma20 is not None:
        stop_pct = float(trading.get("stop_loss_ma20_pct", 0.04))
        stop_loss = round(min(ma20, price * (1 - stop_pct)), 2)

    invalidation = (
        f"MSS 跌破 {macro_veto:.0f} 或触发止损 "
        f"({stop_loss if stop_loss else 'MA20-4%'})"
    )

    return VerdictResult(
        verdict=verdict,
        confidence=confidence,
        mss_final=mss,
        entry_price=entry,
        stop_loss_price=stop_loss,
        invalidation=invalidation,
        reasoning=reasoning,
        downgrade_reasons=downgrade,
        blocked=blocked,
        label_key=label_key,
    )


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)
