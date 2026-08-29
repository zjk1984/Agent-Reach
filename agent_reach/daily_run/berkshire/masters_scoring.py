# -*- coding: utf-8
"""Four-dimension master-style scoring from MSS breakdown + team review."""

from __future__ import annotations

from typing import Any, Optional


def _dim_score(val: float, *, low: float = 30, high: float = 70) -> float:
    if val <= low:
        return 1.0
    if val >= high:
        return 5.0
    return 1.0 + (val - low) / (high - low) * 4.0


def build_masters_scoring(
    snapshot: dict[str, Any],
    *,
    team_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bd = snapshot.get("mss_breakdown") or {}
    technical = float(bd.get("technical") or 50)
    sentiment = float(bd.get("sentiment") or 50)
    global_f = float(bd.get("global") or 50)
    risk = float(bd.get("risk") or 50)
    flow = float(bd.get("flow") or 50)
    quant = float(bd.get("quant") or 50)

    rows = [
        {
            "master": "段永平",
            "dimension": "商业模式",
            "score": round(_dim_score((technical + quant) / 2), 1),
            "note": "技术面+量化反映生意质量 proxy",
        },
        {
            "master": "巴菲特",
            "dimension": "护城河/估值",
            "score": round(_dim_score((technical + flow) / 2), 1),
            "note": "资金流+技术 → 护城河与安全边际 proxy",
        },
        {
            "master": "芒格",
            "dimension": "逆向/风险",
            "score": round(_dim_score(risk, low=40, high=80), 1),
            "note": "risk 因子高=风控压力低",
        },
        {
            "master": "李录",
            "dimension": "长期确定性",
            "score": round(_dim_score((global_f + sentiment) / 2, low=35, high=65), 1),
            "note": "全球+舆情 → 10年确定性 proxy",
        },
    ]

    if team_review:
        counter = str(team_review.get("counter_thesis") or "").strip()
        if counter:
            for r in rows:
                if r["master"] == "芒格":
                    r["note"] = f"反面：{counter[:80]}"
                    r["score"] = max(1.0, r["score"] - 0.5)
        if team_review.get("consensus_label") == "回避":
            for r in rows:
                r["score"] = max(1.0, r["score"] - 1.0)

    avg = sum(r["score"] for r in rows) / len(rows)
    conflict = max(r["score"] for r in rows) - min(r["score"] for r in rows) >= 1.5

    return {
        "rows": rows,
        "average": round(avg, 2),
        "conflict": conflict,
        "headline": _headline(avg, conflict, snapshot),
    }


def _headline(avg: float, conflict: bool, snapshot: dict[str, Any]) -> str:
    verdict = snapshot.get("verdict") or "观察"
    if conflict:
        return f"四维分歧（均分 {avg:.1f}），需看 counter_thesis；标签 {verdict}"
    if avg >= 4.0:
        return f"四维偏强（均分 {avg:.1f}），与 {verdict} 一致"
    if avg >= 3.0:
        return f"四维中性（均分 {avg:.1f}），条件性 {verdict}"
    return f"四维偏弱（均分 {avg:.1f}），倾向防守"


def render_masters_markdown(scoring: dict[str, Any]) -> str:
    lines = [
        "**四维度评分（Berkshire 对抗视角）**",
        scoring.get("headline", ""),
        "",
        "| 视角 | 维度 | 评分 | 说明 |",
        "|------|------|:----:|------|",
    ]
    for r in scoring.get("rows") or []:
        lines.append(
            f"| {r['master']} | {r['dimension']} | {r['score']}/5 | {r.get('note', '')[:60]} |"
        )
    lines.append("")
    lines.append(f"- 均分：**{scoring.get('average')}**/5 · 分歧：{'是' if scoring.get('conflict') else '否'}")
    return "\n".join(lines)
