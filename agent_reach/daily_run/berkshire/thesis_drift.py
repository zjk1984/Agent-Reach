# -*- coding: utf-8
"""Thesis drift detection — fact vs price vs wording changes."""

from __future__ import annotations

from typing import Any, Literal

DriftDir = Literal["Improved", "Unchanged", "Weakened"]


def _dir_delta(old: Any, new: Any, *, higher_is_better: bool = True) -> DriftDir:
    if old is None or new is None:
        return "Unchanged"
    try:
        o, n = float(old), float(new)
    except (TypeError, ValueError):
        if str(old).strip() == str(new).strip():
            return "Unchanged"
        return "Weakened" if not higher_is_better else "Unchanged"
    if abs(n - o) < 0.05:
        return "Unchanged"
    if n > o:
        return "Improved" if higher_is_better else "Weakened"
    return "Weakened" if higher_is_better else "Improved"


def compare_thesis_docs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compare two thesis JSON docs (or baseline vs current snapshot fields)."""
    old_anchor = old.get("valuation_anchor") or {}
    new_anchor = new.get("valuation_anchor") or {}

    dimensions: list[dict[str, Any]] = []

    mss_dir = _dir_delta(old_anchor.get("mss"), new_anchor.get("mss"))
    dimensions.append(
        {
            "dimension": "估值锚点/MSS",
            "old": old_anchor.get("mss"),
            "new": new_anchor.get("mss"),
            "drift": mss_dir,
            "evidence": f"MSS {old_anchor.get('mss')} → {new_anchor.get('mss')}",
        }
    )

    verdict_old = old_anchor.get("verdict")
    verdict_new = new_anchor.get("verdict")
    verdict_order = {"回避": 0, "观察": 1, "可做": 2}
    v_dir: DriftDir = "Unchanged"
    if verdict_old != verdict_new:
        o = verdict_order.get(str(verdict_old), 1)
        n = verdict_order.get(str(verdict_new), 1)
        if n > o:
            v_dir = "Improved"
        elif n < o:
            v_dir = "Weakened"
    dimensions.append(
        {
            "dimension": "结论标签",
            "old": verdict_old,
            "new": verdict_new,
            "drift": v_dir,
            "evidence": f"{verdict_old} → {verdict_new}" if verdict_old != verdict_new else "—",
        }
    )

    price_dir = _dir_delta(old_anchor.get("price"), new_anchor.get("price"), higher_is_better=False)
    dimensions.append(
        {
            "dimension": "股价",
            "old": old_anchor.get("price"),
            "new": new_anchor.get("price"),
            "drift": price_dir,
            "evidence": "价格变化≠论文漂移，需结合 MSS/基本面",
        }
    )

    weakened = sum(1 for d in dimensions if d["drift"] == "Weakened")
    improved = sum(1 for d in dimensions if d["drift"] == "Improved")
    if weakened >= 2:
        overall = "负向漂移"
    elif improved >= 2 and weakened == 0:
        overall = "正向漂移"
    elif weakened == 1:
        overall = "边际弱化"
    else:
        overall = "未漂移"

    return {
        "overall": overall,
        "dimensions": dimensions,
        "weakened_count": weakened,
        "improved_count": improved,
    }


def detect_thesis_drift(
    code: str,
    current_snapshot: dict[str, Any],
    *,
    settings: dict | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled
    from agent_reach.daily_run.berkshire.thesis_tracker import load_thesis, sync_thesis_from_snapshot

    if not berkshire_enabled(settings, key="thesis_drift_on_close"):
        return {"skipped": True, "reason": "berkshire.thesis_drift_on_close disabled"}

    old = load_thesis(code, settings)
    if old is None:
        sync_thesis_from_snapshot(current_snapshot, settings=settings, phase="close")
        return {"skipped": True, "reason": "no baseline thesis; created initial"}

    new_doc = dict(old)
    new_doc["valuation_anchor"] = {
        "price": current_snapshot.get("price"),
        "mss": current_snapshot.get("mss_final"),
        "verdict": current_snapshot.get("verdict"),
        "as_of": current_snapshot.get("as_of"),
    }
    report = compare_thesis_docs(old, new_doc)
    report["code"] = code
    report["name"] = current_snapshot.get("name") or code
    return report


def render_drift_markdown(report: dict[str, Any]) -> str:
    if report.get("skipped"):
        return f"**论文漂移：** 跳过 — {report.get('reason', '')}"
    lines = [
        f"**论文漂移** · {report.get('name')} ({report.get('code')})",
        f"- 总体：**{report.get('overall')}**",
        "",
        "| 维度 | 旧 | 新 | 漂移 |",
        "|------|----|----|------|",
    ]
    for d in report.get("dimensions") or []:
        lines.append(
            f"| {d['dimension']} | {d.get('old', '—')} | {d.get('new', '—')} | {d.get('drift')} |"
        )
    return "\n".join(lines)
