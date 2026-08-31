# -*- coding: utf-8
"""DeepSeek interpretation card — code computes, model interprets."""

from __future__ import annotations

from typing import Any, Callable, Optional

from agent_reach.daily_run.report_push import ReportSection

DEEPSEEK_USAGE_PRINCIPLE = (
    "计算用代码，解读用模型：价格、涨跌幅、仓位、收益率、触发条件等数字"
    "必须由量化系统确定性计算；DeepSeek 只负责把这些数字翻译成自然语言、"
    "生成解读文本、提取文本信息；禁止模型做任何影响交易决策的数值判断。"
)

DEEPSEEK_NARRATIVE_RULE = (
    "仅解读输入中已给出的数字，不得推算、修改或新增价格/涨跌幅/仓位/收益率/触发条件；"
    "不得给出新的买卖价位、目标仓位、止损位或加仓比例。"
)

_CATEGORY = "deepseek_interpretation"
_INTRADAY_JOBS = frozenset({"intraday"})
_LLM_BODY_KEYS = ("focus_points", "divergence_notes", "risk_alerts", "trade_operations")


def interpretation_card_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = dict((settings or {}).get("report") or {}).get("deepseek_interpretation_card") or {}
    if cfg.get("enabled") is False:
        return False
    return True


def interpretation_card_label(narrative: Optional[dict[str, Any]]) -> str:
    if str((narrative or {}).get("planner") or "") == "llm":
        return "🤖 DeepSeek 解读"
    return "📋 规则解读"


def _render_llm_interpretation_body(narrative: dict[str, Any]) -> str:
    """DeepSeek card: summary + LLM bullet fields only (no harness/meta sections)."""
    lines: list[str] = []
    summary = str(narrative.get("summary") or "").strip()
    if summary:
        lines.append(summary)
    for key in _LLM_BODY_KEYS:
        for item in narrative.get(key) or []:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines).strip()


def render_deepseek_interpretation_markdown(
    narrative: Optional[dict[str, Any]],
    *,
    job: str,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    """Render final interpretation card body. Intraday never uses DeepSeek."""
    if job in _INTRADAY_JOBS:
        return ""
    if not interpretation_card_enabled(settings):
        return ""
    if not narrative or narrative.get("skipped"):
        return ""
    planner = str(narrative.get("planner") or "deterministic")
    if planner == "llm":
        return _render_llm_interpretation_body(narrative)
    from agent_reach.daily_run.report_narrative import render_narrative_markdown

    return render_narrative_markdown(narrative, job=job).strip()


def append_interpretation_report_section(
    sections: list[ReportSection],
    narrative: Optional[dict[str, Any]],
    *,
    job: str,
    settings: Optional[dict[str, Any]] = None,
    renumber: Optional[Callable[[list[ReportSection]], None]] = None,
) -> list[ReportSection]:
    body = render_deepseek_interpretation_markdown(narrative, job=job, settings=settings)
    if not body.strip():
        return sections
    out = list(sections)
    out.append(ReportSection(category=_CATEGORY, title="", body=body))
    if renumber:
        renumber(out)
    return out


def append_interpretation_label_section(
    sections: list[Any],
    narrative: Optional[dict[str, Any]],
    *,
    job: str,
    settings: Optional[dict[str, Any]] = None,
    section_factory: Callable[[str, str], Any],
) -> list[Any]:
    body = render_deepseek_interpretation_markdown(narrative, job=job, settings=settings)
    if not body.strip():
        return sections
    label = "DeepSeek解读" if str((narrative or {}).get("planner") or "") == "llm" else "规则解读"
    out = list(sections)
    out.append(section_factory(label, body))
    return out
