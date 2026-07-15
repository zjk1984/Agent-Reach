# -*- coding: utf-8
"""Intraday MSS curve fitting and close narrative."""

from __future__ import annotations

from typing import Any, Optional


def analyze_intraday_curve(
    mss_values: list[float],
    *,
    predicted_range: Optional[tuple[float, float]] = None,
    scan_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Polynomial-lite curve analysis on S1-Sn MSS series."""
    if not mss_values:
        return {"summary": "无盘中 MSS 数据", "points": 0, "scan_ids": []}

    n = len(mss_values)
    xs = list(range(n))
    ys = [float(v) for v in mss_values]
    labels = list(scan_ids or [f"S{i + 1}" for i in range(n)])

    # Linear regression slope (1st derivative proxy)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n)) or 1
    slope = num / den

    # Acceleration: compare first vs second half slopes
    accel = 0.0
    if n >= 4:
        mid = n // 2
        slope1 = _slope(ys[:mid])
        slope2 = _slope(ys[mid:])
        accel = slope2 - slope1

    trend = _classify_trend(slope, accel)
    summary = f"盘中 MSS {ys[0]:.0f}→{ys[-1]:.0f}，趋势 {trend}（斜率 {slope:+.2f}/scan）"

    hit = None
    deviation = None
    if predicted_range and len(predicted_range) == 2:
        lo, hi = float(predicted_range[0]), float(predicted_range[1])
        actual_min, actual_max = min(ys), max(ys)
        hit = actual_min >= lo and actual_max <= hi
        if ys[-1] < lo:
            deviation = f"尾盘 MSS {ys[-1]:.0f} 低于预测下沿 {lo:.0f}"
        elif ys[-1] > hi:
            deviation = f"尾盘 MSS {ys[-1]:.0f} 高于预测上沿 {hi:.0f}"

    return {
        "points": n,
        "values": ys,
        "scan_ids": labels,
        "slope": round(slope, 3),
        "acceleration": round(accel, 3),
        "trend": trend,
        "summary": summary,
        "prediction_hit": hit,
        "deviation": deviation,
    }


def render_curve_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "**📈 盘中 MSS 曲线**",
        "",
        analysis.get("summary", ""),
    ]
    n = int(analysis.get("points") or 0)
    if n > 0:
        labels = analysis.get("scan_ids") or [f"S{i + 1}" for i in range(n)]
        values = analysis.get("values") or []
        seq = " → ".join(f"{labels[i]}={values[i]:.0f}" for i in range(n) if i < len(values))
        lines.append(f"- 扫描次数：**{n}** 次（{' · '.join(labels)}）")
        if seq:
            lines.append(f"- MSS 序列：{seq}")
    lines.extend([
        f"- 斜率：{analysis.get('slope', '—')} · 加速度：{analysis.get('acceleration', '—')}",
        f"- 趋势研判：**{analysis.get('trend', '—')}**",
    ])
    if analysis.get("prediction_hit") is not None:
        hit = "✅ 命中" if analysis["prediction_hit"] else "❌ 偏离"
        lines.append(f"- 预测区间：{hit}")
    if analysis.get("deviation"):
        lines.append(f"- 偏差：{analysis['deviation']}")
    return "\n".join(lines)


def _slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n)) or 1
    return num / den


def _classify_trend(slope: float, accel: float) -> str:
    if slope > 0.5 and accel > 0:
        return "加速反弹"
    if slope > 0.3:
        return "震荡走强"
    if slope < -0.5 and accel < 0:
        return "加速杀跌"
    if slope < -0.3:
        return "震荡走弱"
    if abs(slope) <= 0.3 and accel > 0:
        return "减速筑底"
    return "横盘震荡"
