# -*- coding: utf-8
"""Midday Feishu cards — half-day verify + afternoon plan (3–4 cards, no close-style depth)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_reach.daily_run.report_push import ReportSection
from agent_reach.daily_run.snapshot_builder import _normalize_code

MIDDAY_CARD_ORDER: tuple[str, ...] = (
    "plan_verify",
    "session_brief",
    "afternoon_risk",
)

MIDDAY_CARD_LABELS: dict[str, str] = {
    "plan_verify": "📋 早盘验证 · 下午调整",
    "session_brief": "☀️ 半天速览",
    "afternoon_risk": "⚠️ 下午风险提醒",
}


def midday_card_layout_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = (settings or {}).get("report") or {}
    layout = str(cfg.get("midday_card_layout", "cards")).lower()
    return layout not in ("legacy", "old", "false", "0")


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class MiddayCardContext:
    plan_rows: list[dict[str, Any]] = field(default_factory=list)
    plan_unchanged: bool = True
    session_brief: dict[str, Any] = field(default_factory=dict)
    risk_lines: list[str] = field(default_factory=list)
    audit_banner: str = ""
    settings: Optional[dict[str, Any]] = None


def _morning_plan_text(action: dict[str, Any]) -> str:
    trigger = str(action.get("trigger") or "").strip()
    operation = str(action.get("operation") or "").strip()
    target = str(action.get("target_position") or "").strip()
    if trigger and trigger != "—":
        if operation and operation not in trigger:
            return f"{operation} · {trigger}"
        return trigger
    if target:
        return f"{operation} · {target}" if operation else target
    return operation or "—"


def _scan_num(scan_id: object) -> Optional[int]:
    raw = str(scan_id or "").strip().upper()
    if raw.startswith("S") and raw[1:].isdigit():
        return int(raw[1:])
    return None


def _am_scans(state: dict[str, Any]) -> list[dict[str, Any]]:
    scans = list(state.get("scans") or [])
    am: list[dict[str, Any]] = []
    for scan in scans:
        src = str(scan.get("source") or "")
        sid = _scan_num(scan.get("scan_id"))
        if src == "midday":
            continue
        if sid is not None and sid <= 7:
            am.append(scan)
        elif src in {"morning", ""}:
            am.append(scan)
    return am or scans[:-1] if len(scans) > 1 else scans


def _holding_for_code(enriched: dict[str, Any], code: str) -> dict[str, Any]:
    pf = enriched.get("portfolio") or {}
    for row in pf.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) == code:
            return dict(row)
    return {}


def _snapshot_fields(enriched: dict[str, Any], code: str) -> dict[str, Any]:
    if _normalize_code(str(enriched.get("code") or "")) == code:
        return dict(enriched)
    return {}


def _session_price_stats(
    holding: dict[str, Any],
    snapshot: dict[str, Any],
    am_scans: list[dict[str, Any]],
) -> dict[str, Optional[float]]:
    prices: list[float] = []
    for key in ("open", "price", "high", "low"):
        val = _optional_float(holding.get(key) if key in holding else snapshot.get(key))
        if val is not None and val > 0:
            prices.append(val)
    for scan in am_scans:
        px = _optional_float(scan.get("price"))
        if px is not None and px > 0:
            prices.append(px)
    open_px = _optional_float(holding.get("open") or snapshot.get("open"))
    price = _optional_float(holding.get("price") or snapshot.get("price"))
    high = max(prices) if prices else None
    low = min(prices) if prices else None
    return {"open": open_px, "price": price, "high": high, "low": low}


def _change_pct(holding: dict[str, Any], snapshot: dict[str, Any]) -> Optional[float]:
    from agent_reach.daily_run.close_morning_handoff import _describe_actual_move

    _text, pct = _describe_actual_move(holding, snapshot)
    return pct


def _parse_level_from_text(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?", str(text or ""))
    if match:
        return float(match.group(1))
    return None


def _verify_plan(
    *,
    morning_plan: str,
    operation: str,
    trigger: str,
    stats: dict[str, Optional[float]],
    change_pct: Optional[float],
) -> tuple[str, str, str]:
    """Return (am_actual, verify_icon, verify_label)."""
    low = stats.get("low")
    high = stats.get("high")
    price = stats.get("price")
    open_px = stats.get("open")
    plan_lower = morning_plan.lower()
    trig = str(trigger or morning_plan)

    level = _parse_level_from_text(trig)
    if "跌破" in trig or "≤" in trig or ("减" in operation and level is not None):
        if level is not None and low is not None and low <= level:
            return f"最低{low:.2f}，已触发", "✅", "已触发"
        if level is not None and low is not None:
            return f"最低{low:.2f}，未触发", "❌", "未触发"
    if "突破" in trig or "≥" in trig or ("加" in operation and level is not None):
        if level is not None and high is not None and high >= level:
            return f"最高{high:.2f}，已触发", "✅", "已触发"
        if level is not None and high is not None:
            return f"最高{high:.2f}，未触发", "❌", "未触发"

    if operation in ("观望", "持有") or "观望" in plan_lower:
        if change_pct is not None:
            if change_pct >= 1.0 and open_px is not None and price is not None and price > open_px:
                return f"低开高走，{change_pct:+.1f}%", "⚠️", "超预期"
            if change_pct <= -1.0:
                return f"走弱 {change_pct:+.1f}%", "⚠️", "偏弱"
            return f"波动 {change_pct:+.1f}%", "✅", "符合预期"
        return "—", "—", "待确认"

    if change_pct is not None:
        return f"上午 {change_pct:+.1f}%", "✅" if abs(change_pct) <= 2 else "⚠️", "已观察"
    return "数据不足", "—", "待确认"


def _afternoon_action(
    *,
    morning_plan: str,
    operation: str,
    trigger: str,
    verify_icon: str,
    verify_label: str,
    target_weight: Optional[float],
    current_weight: Optional[float],
    stats: dict[str, Optional[float]],
    changed: bool,
) -> tuple[str, bool]:
    """Return (afternoon_action_markdown, is_changed)."""
    target_s = f"{target_weight:.0f}%" if target_weight is not None else "原目标"
    maintain = f"维持{target_s}仓位" if target_weight is not None else "维持原仓位"
    stop = _parse_level_from_text(trigger)
    low = stats.get("low")

    if verify_icon == "✅" and verify_label == "已触发":
        if operation == "减仓":
            return maintain, False
        if operation == "加仓":
            return f"按计划加仓至 **{target_s}**", True

    if verify_icon == "❌" and "未触发" in verify_label:
        if operation == "加仓" and stop is not None:
            stop_loss = round(stop * 0.95, 2) if stop > 1 else stop
            return f"继续等待，跌破 **{stop_loss:.2f}** 止损", False
        if operation == "减仓":
            return maintain, False
        return "继续等待触发条件", False

    if verify_icon == "⚠️" and verify_label == "超预期":
        rebound = stats.get("high") or stats.get("price")
        if rebound is not None:
            return f"反弹至 **{rebound:.1f}** 减仓", True
        return "**超预期**，下午择机减仓", True

    if not changed:
        if operation in ("观望", "持有"):
            return "下午维持观望", False
        return maintain, False

    return f"**{morning_plan}** → {maintain}", True


def build_midday_plan_rows(
    *,
    morning_handoff: Optional[dict[str, Any]],
    enriched: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    actions = list((morning_handoff or {}).get("action_checklist") or [])
    if not actions:
        return []

    am_scans = _am_scans(state)
    rows: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        code = _normalize_code(str(action.get("code") or ""))
        name = str(action.get("name") or code or "—")
        operation = str(action.get("operation") or "")
        trigger = str(action.get("trigger") or "")
        morning_plan = _morning_plan_text(action)
        holding = _holding_for_code(enriched, code)
        snapshot = _snapshot_fields(enriched, code)
        stats = _session_price_stats(holding, snapshot, am_scans)
        change_pct = _change_pct(holding, snapshot)
        target_weight = _optional_float(action.get("target_weight_pct"))
        current_weight = _optional_float(action.get("current_weight_pct"))

        am_actual, verify_icon, verify_label = _verify_plan(
            morning_plan=morning_plan,
            operation=operation,
            trigger=trigger,
            stats=stats,
            change_pct=change_pct,
        )
        afternoon, changed = _afternoon_action(
            morning_plan=morning_plan,
            operation=operation,
            trigger=trigger,
            verify_icon=verify_icon,
            verify_label=verify_label,
            target_weight=target_weight,
            current_weight=current_weight,
            stats=stats,
            changed=False,
        )
        rows.append(
            {
                "code": code,
                "name": name,
                "morning_plan": morning_plan,
                "am_actual": am_actual,
                "verify": f"{verify_icon} {verify_label}".strip(),
                "afternoon_action": afternoon,
                "changed": changed,
            }
        )
    return rows


def build_midday_card_context(
    scan_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    audit: Any = None,
) -> MiddayCardContext:
    from agent_reach.daily_run.close_morning_handoff import load_morning_handoff, render_risk_tracking_markdown
    from agent_reach.daily_run.morning_cards import MorningCardContext, MorningSymbolRow
    from agent_reach.daily_run.trade_calendar import today_shanghai

    enriched = dict(scan_result.get("enriched") or {})
    state = dict(scan_result.get("state") or {})
    scan = dict(scan_result.get("scan") or {})
    morning_handoff = load_morning_handoff(morning_day=today_shanghai())

    plan_rows = build_midday_plan_rows(
        morning_handoff=morning_handoff,
        enriched=enriched,
        state=state,
    )
    plan_unchanged = not plan_rows or not any(r.get("changed") for r in plan_rows)

    trend_map = {
        "rising": "上升",
        "falling": "下降",
        "turning_up": "拐点向上",
        "turning_down": "拐点向下",
        "flat": "横盘",
        "mixed": "震荡",
        "insufficient": "数据不足",
    }
    am_scans = _am_scans(state)
    last_am = am_scans[-1] if am_scans else scan
    session_brief = {
        "last_scan_id": last_am.get("scan_id") or scan.get("reference_scan_id") or "—",
        "mss": last_am.get("mss_final") or scan.get("mss_final"),
        "verdict": last_am.get("verdict") or scan.get("verdict") or "观察",
        "lookback_mss": scan_result.get("lookback_mss"),
        "trend": trend_map.get(
            str(scan_result.get("anchor_trend") or scan_result.get("trend") or "flat"),
            "横盘",
        ),
    }

    risk_lines: list[str] = []
    pf = dict(enriched.get("portfolio") or {})
    code = str(enriched.get("code") or scan.get("code") or "")
    holding = _holding_for_code(enriched, code)
    pseudo_ctx = MorningCardContext(
        portfolio=pf,
        symbol_rows=[
            MorningSymbolRow(
                code=code,
                name=str(enriched.get("name") or scan.get("name") or code),
                holding=holding,
                report=(scan_result.get("evaluation") or {}).get("report") or {},
                snapshot=enriched,
            )
        ],
        settings=settings,
    )
    risk_lines.extend(render_risk_tracking_markdown(pseudo_ctx))

    trend = str(scan_result.get("anchor_trend") or scan_result.get("trend") or "")
    verdict = str(session_brief.get("verdict") or "")
    if verdict in {"回避", "观察"} and trend in {"falling", "turning_down"}:
        risk_lines.append("- 上午 MSS 未确认进攻，**下午宜守现金或轻仓试探**")
    if scan.get("record_scan_skipped"):
        risk_lines.append("- 12:30 不写入 MSS 扫描，**13:05 起以 S8+ 扫描确认**")

    audit_banner = ""
    if audit is not None and (not getattr(audit, "passed", True) or getattr(audit, "warnings", None)):
        parts = ["**⚠️ 数据审计提示**"]
        if not getattr(audit, "passed", True):
            parts.append("；".join(getattr(audit, "issues", []) or []))
        for w in getattr(audit, "warnings", []) or []:
            parts.append(f"- {w}")
        audit_banner = "\n".join(parts)

    return MiddayCardContext(
        plan_rows=plan_rows,
        plan_unchanged=plan_unchanged,
        session_brief=session_brief,
        risk_lines=risk_lines[:6],
        audit_banner=audit_banner,
        settings=settings,
    )


def render_plan_verify_markdown(ctx: MiddayCardContext) -> str:
    lines: list[str] = []
    if ctx.audit_banner:
        lines.extend([ctx.audit_banner, "", "---", ""])

    if ctx.plan_unchanged:
        lines.append("**✅ 早盘计划不变，下午维持原策略**")
    else:
        lines.append("**下午操作调整（相对早盘计划）**")

    if not ctx.plan_rows:
        lines.extend(["", "- 无早盘操作清单，下午维持持仓观察"])
        return "\n".join(lines).strip()

    lines.extend(
        [
            "",
            "| 股票 | 早盘计划 | 上午实际 | 验证结果 | 下午操作 |",
            "|------|----------|----------|----------|----------|",
        ]
    )
    for row in ctx.plan_rows:
        afternoon = str(row.get("afternoon_action") or "—")
        if row.get("changed") and "**" not in afternoon:
            afternoon = f"**{afternoon}**"
        lines.append(
            f"| {row.get('name')} | {row.get('morning_plan')} | {row.get('am_actual')} "
            f"| {row.get('verify')} | {afternoon} |"
        )
    return "\n".join(lines).strip()


def render_session_brief_markdown(ctx: MiddayCardContext) -> str:
    brief = ctx.session_brief or {}
    if not brief:
        return ""
    lines = [
        f"- **上午末扫 {brief.get('last_scan_id')}：** MSS **{brief.get('mss', '—')}** · "
        f"**{brief.get('verdict', '观察')}**",
    ]
    if brief.get("lookback_mss") is not None:
        lines.append(
            f"- **Lookback：** {float(brief['lookback_mss']):.1f} 分 · 趋势 **{brief.get('trend', '—')}**"
        )
    lines.append("- _13:05 起常规盘中扫描确认，勿仅凭午休信息激进调仓_")
    return "\n".join(lines).strip()


def render_afternoon_risk_markdown(ctx: MiddayCardContext) -> str:
    if not ctx.risk_lines:
        return "- 暂无新增下午风险提醒"
    return "\n".join(ctx.risk_lines[:6]).strip()


_CARD_RENDERERS = {
    "plan_verify": render_plan_verify_markdown,
    "session_brief": render_session_brief_markdown,
    "afternoon_risk": render_afternoon_risk_markdown,
}


def render_midday_card_sections(ctx: MiddayCardContext) -> list[ReportSection]:
    sections: list[ReportSection] = []
    for category in MIDDAY_CARD_ORDER:
        renderer = _CARD_RENDERERS[category]
        body = renderer(ctx)
        if not (body or "").strip():
            continue
        sections.append(ReportSection(category=category, title="", body=body.strip()))
    total = len(sections)
    for i, sec in enumerate(sections, start=1):
        label = MIDDAY_CARD_LABELS.get(sec.category, sec.category)
        sec.title = f"{label} {i}/{total}"
    return sections


def render_midday_cards_markdown(ctx: MiddayCardContext) -> str:
    parts = [sec.body for sec in render_midday_card_sections(ctx) if sec.body.strip()]
    return "\n\n---\n\n".join(parts).strip()
