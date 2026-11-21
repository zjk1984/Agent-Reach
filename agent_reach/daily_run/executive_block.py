# -*- coding: utf-8
"""Tier-A Executive markdown block for Feishu daily-run cards."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai

EXECUTIVE_REPORT_TYPES = frozenset({"premarket", "verify", "intraday"})


def executive_block_enabled(settings: dict[str, Any]) -> bool:
    tier = ((settings.get("report") or {}).get("card_tier") or {})
    return tier.get("executive_enabled", True) is not False


def _report_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("report") or {}


def _job_for_report_type(report_type: str) -> str:
    return {
        "premarket": "morning",
        "verify": "close",
        "intraday": "intraday",
        "midday": "midday",
    }.get(report_type, report_type)


def _fmt_money_signed(value: Any) -> str:
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if amount >= 0 else ""
    return f"{sign}¥{amount:,.0f}"


def _fmt_pct_points(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _primary_mss_verdict(report: dict[str, Any]) -> tuple[Any, str]:
    mss = report.get("mss_final")
    verdict = report.get("verdict")
    if mss is None:
        mss = report.get("mss_current")
    if verdict is None:
        verdict = report.get("verdict_current")
    return mss if mss is not None else "—", str(verdict or "—")


def _gate_summary(settings: dict[str, Any], portfolio_summary: Optional[dict[str, Any]]) -> str:
    from agent_reach.daily_run.harness_policy import macro_veto_default, min_cash_ratio_default

    macro_veto = macro_veto_default(settings)
    min_cash = min_cash_ratio_default(settings)
    pf = portfolio_summary or {}
    cash_ratio = pf.get("cash_ratio")
    if cash_ratio is None:
        min_cash_flag = "—"
    else:
        try:
            min_cash_flag = "OK" if float(cash_ratio) >= float(min_cash) else "LOW"
        except (TypeError, ValueError):
            min_cash_flag = "—"
    return f"macro_veto={macro_veto:.0f} · min_cash={min_cash_flag}"


def build_executive_context(
    job: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    portfolio_summary: Optional[dict[str, Any]] = None,
    primary_report: Optional[dict[str, Any]] = None,
    decision_closure_line: Optional[str] = None,
    tsp_line: Optional[str] = None,
    anomalies: Optional[list[str]] = None,
    as_of: Optional[str] = None,
    exit_code: int = 0,
) -> dict[str, Any]:
    return {
        "job": job,
        "settings": settings or {},
        "portfolio_summary": portfolio_summary or {},
        "primary_report": primary_report or {},
        "decision_closure_line": decision_closure_line,
        "tsp_line": tsp_line,
        "anomalies": list(anomalies or []),
        "as_of": as_of or today_shanghai().isoformat(),
        "exit_code": exit_code,
    }


def format_executive_block(
    *,
    report_type: str,
    settings: dict[str, Any],
    context: dict[str, Any],
    split: bool,
    section_count: int,
) -> str:
    if report_type not in EXECUTIVE_REPORT_TYPES:
        return ""
    job = str(context.get("job") or _job_for_report_type(report_type))
    day = str(context.get("as_of") or today_shanghai().isoformat())
    exit_code = int(context.get("exit_code") or 0)
    if split and section_count > 1:
        push_mode = f"split/{section_count}"
    else:
        push_mode = "single"

    lines: list[str] = [
        "**📌 Executive**",
        "",
        f"`job={job}` · `exit={exit_code}` · `push={push_mode}` · `{day}`",
    ]

    pf = context.get("portfolio_summary") or {}
    daily_pnl = pf.get("daily_pnl")
    daily_pnl_pct = pf.get("daily_pnl_pct")
    if daily_pnl is not None:
        bench = pf.get("benchmark_vs_portfolio") or pf.get("vs_benchmark_line")
        bench_s = f" · {bench}" if bench else ""
        lines.append(
            f"**PnL:** {_fmt_money_signed(daily_pnl)} ({_fmt_pct_points(daily_pnl_pct)}){bench_s}"
        )
    elif pf.get("end_total") is not None:
        try:
            lines.append(f"**净值:** ¥{float(pf['end_total']):,.0f}")
        except (TypeError, ValueError):
            pass
    elif pf.get("nav") is not None:
        try:
            lines.append(f"**NAV:** ¥{float(pf['nav']):,.0f}")
        except (TypeError, ValueError):
            pass

    report = context.get("primary_report") or {}
    if report:
        name = report.get("name") or report.get("code") or "主标的"
        code = report.get("code")
        label = f"{name} ({code})" if code and name != code else str(name)
        mss, verdict = _primary_mss_verdict(report)
        lines.append(f"**MSS/结论:** {label} · **{mss}** · {verdict}")

    tsp_line = (context.get("tsp_line") or "").strip()
    if tsp_line:
        lines.append(tsp_line)

    gate = _gate_summary(settings, pf)
    lines.append(f"**gate:** {gate}")

    closure_line = (context.get("decision_closure_line") or "").strip()
    if closure_line:
        lines.append(closure_line.lstrip("- ").strip())

    anomalies = [str(a).strip() for a in (context.get("anomalies") or []) if str(a).strip()]
    if anomalies:
        lines.append("**异常:** " + "；".join(anomalies[:4]))
    else:
        audit_issues = pf.get("audit_issues") or []
        if audit_issues:
            lines.append("**异常:** " + "；".join(str(x) for x in audit_issues[:3]))
        else:
            lines.append("**异常:** 无")

    return "\n".join(lines).strip()


def prepend_executive_block(
    body: str,
    *,
    report_type: str,
    settings: dict[str, Any],
    context: Optional[dict[str, Any]],
    split: bool = False,
    section_count: int = 1,
) -> str:
    if not context or not executive_block_enabled(settings):
        return body
    block = format_executive_block(
        report_type=report_type,
        settings=settings,
        context=context,
        split=split,
        section_count=section_count,
    )
    if not block:
        return body
    body = body.strip()
    if not body:
        return block
    return f"{block}\n\n---\n\n{body}"