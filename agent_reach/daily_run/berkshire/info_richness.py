# -*- coding: utf-8
"""A/B/C information richness rating — anti 'more data = more certainty' bias."""

from __future__ import annotations

from typing import Any, Literal

RichnessGrade = Literal["A", "B", "C"]


def grade_info_richness(snapshot: dict[str, Any], audit: Any | None = None) -> dict[str, Any]:
    """Rate data completeness for decision confidence."""
    score = 0
    signals: list[str] = []

    if snapshot.get("price") is not None:
        score += 1
    else:
        signals.append("缺实时报价")

    breakdown = snapshot.get("mss_breakdown") or {}
    filled_dims = sum(1 for k, v in breakdown.items() if not str(k).startswith("_") and v is not None)
    if filled_dims >= 6:
        score += 2
    elif filled_dims >= 4:
        score += 1
    else:
        signals.append(f"MSS 因子仅 {filled_dims} 维")

    if snapshot.get("ma20") is not None:
        score += 1
    if snapshot.get("volume") is not None:
        score += 1

    audit_passed = True
    audit_issues = 0
    if audit is not None:
        audit_passed = getattr(audit, "passed", audit.get("passed") if isinstance(audit, dict) else True)
        if not audit_passed:
            audit_issues = len(getattr(audit, "issues", []) or (audit.get("issues") if isinstance(audit, dict) else []))

    if audit_passed:
        score += 1
    else:
        signals.append(f"审计未通过({audit_issues}项)")

    macro = snapshot.get("macro_summary") or snapshot.get("text_feed") or ""
    if len(str(macro)) > 80:
        score += 1

    if score >= 6:
        grade: RichnessGrade = "A"
        note = "数据充裕；仍须警惕共识陷阱"
    elif score >= 4:
        grade = "B"
        note = "数据有限，推算指标需标注置信度"
    else:
        grade = "C"
        note = "信息稀缺，结论应为灰色/观察，禁止激进建仓"

    blocks_aggressive = grade == "C" or (grade == "B" and not audit_passed)

    return {
        "grade": grade,
        "score": score,
        "note": note,
        "signals": signals,
        "blocks_aggressive": blocks_aggressive,
    }


def render_richness_line(richness: dict[str, Any]) -> str:
    grade = richness.get("grade", "?")
    note = richness.get("note", "")
    return f"信息丰富度 **{grade}级** — {note}"
