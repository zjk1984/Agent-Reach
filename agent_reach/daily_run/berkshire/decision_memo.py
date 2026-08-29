# -*- coding: utf-8
"""Forced decision memo — pass / gray / veto with tiered action bands."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_policy import aggressive_entry_default, macro_veto_default


def build_decision_memo(
    snapshot: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    richness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.settings import effective_settings

    cfg = effective_settings(settings)
    mss = snapshot.get("mss_final")
    if mss is None:
        bd = snapshot.get("mss_breakdown") or {}
        from agent_reach.daily_run.verdict import compute_mss

        mss = compute_mss(bd, cfg)
    mss_f = float(mss) if mss is not None else 0.0
    verdict = str(snapshot.get("verdict") or "观察")
    macro_veto = macro_veto_default(cfg)
    aggressive = aggressive_entry_default(cfg)
    price = snapshot.get("price")
    ma20 = snapshot.get("ma20")

    if mss_f < macro_veto:
        decision = "不通过"
        summary = f"MSS {mss_f:.0f} 低于否决线 {macro_veto:.0f}"
    elif verdict == "回避":
        decision = "不通过"
        summary = "标签回避，禁止进攻"
    elif richness and richness.get("blocks_aggressive"):
        decision = "灰色地带"
        summary = f"信息{richness.get('grade')}级，禁止激进建仓"
    elif mss_f >= aggressive and verdict == "可做":
        decision = "通过"
        summary = f"MSS {mss_f:.0f} 达进攻阈值，可条件性建仓"
    elif mss_f >= macro_veto:
        decision = "灰色地带"
        summary = f"MSS {mss_f:.0f} 在观察区（{macro_veto:.0f}–{aggressive:.0f}）"
    else:
        decision = "不通过"
        summary = "未达最低标准"

    tiers = _action_tiers(mss_f, price, ma20, macro_veto, aggressive, decision, cfg)
    invalidation = f"MSS 跌破 {macro_veto:.0f}"
    if price and ma20:
        invalidation += f" 或跌破 MA20 ({ma20})"

    return {
        "decision": decision,
        "summary": summary,
        "tiers": tiers,
        "invalidation": invalidation,
        "mirror_test": _mirror_test(snapshot, mss_f, verdict),
    }


def _action_tiers(
    mss: float,
    price: Any,
    ma20: Any,
    macro_veto: float,
    aggressive: float,
    decision: str,
    cfg: dict,
) -> list[dict[str, str]]:
    if decision == "不通过":
        return [
            {"strategy": "激进型", "action": "禁止", "band": "—"},
            {"strategy": "稳健型", "action": "观望", "band": "—"},
            {"strategy": "保守型", "action": "回避", "band": "—"},
        ]
    if decision == "灰色地带":
        return [
            {"strategy": "激进型", "action": "小仓试探 ≤10%", "band": f"MSS≥{aggressive:.0f} 且 audit 通过"},
            {"strategy": "稳健型", "action": "观望", "band": "等 lookback 确认"},
            {"strategy": "保守型", "action": "不入观察池外新仓", "band": "—"},
        ]
    band = "—"
    if price and ma20:
        try:
            p, m = float(price), float(ma20)
            band = f"¥{m * 0.98:.2f}–¥{p:.2f}（MA20 附近）"
        except (TypeError, ValueError):
            band = f"MSS≥{aggressive:.0f}"
    return [
        {"strategy": "激进型", "action": "可建仓 20%", "band": band},
        {"strategy": "稳健型", "action": "等回踩或 S4+ 确认", "band": band},
        {"strategy": "保守型", "action": "仅持有不加仓", "band": "—"},
    ]


def _mirror_test(snapshot: dict[str, Any], mss: float, verdict: str) -> str:
    name = snapshot.get("name") or snapshot.get("code") or "标的"
    return f"{name}：MSS {mss:.0f}·{verdict}，宏观+技术共振，5句内可复述则保留。"


def render_decision_memo_markdown(memo: dict[str, Any]) -> str:
    lines = [
        f"**决策结论：{memo.get('decision')}** — {memo.get('summary')}",
        "",
        "| 策略 | 建议 | 条件/区间 |",
        "|------|------|-----------|",
    ]
    for t in memo.get("tiers") or []:
        lines.append(f"| {t.get('strategy')} | {t.get('action')} | {t.get('band')} |")
    lines.append("")
    lines.append(f"- 失效条件：{memo.get('invalidation')}")
    lines.append(f"- 镜子测试：{memo.get('mirror_test')}")
    return "\n".join(lines)
