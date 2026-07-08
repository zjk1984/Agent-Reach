# -*- coding: utf-8 -*-
"""Intraday scan (S1-S10) and trade (T1-T5) workflow with lookback MSS."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.lookback import compute_lookback_mss, detect_mss_trend
from agent_reach.daily_run.pipeline import evaluate_snapshot, render_markdown
from agent_reach.daily_run.plugins.loader import run_experts
from agent_reach.daily_run.settings import load_settings


MAX_SCANS = 10
MAX_TRADES = 5


@dataclass
class TradeDecision:
    action: str  # buy | sell | hold | skip
    trade_id: Optional[str]
    lookback_mss: float
    lookback_detail: list[dict[str, Any]]
    trend: str
    reasoning: str
    blocked: bool = False
    friction_blocked: bool = False
    expected_return_pct: Optional[float] = None
    evaluation: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "trade_id": self.trade_id,
            "lookback_mss": self.lookback_mss,
            "lookback_detail": self.lookback_detail,
            "trend": self.trend,
            "reasoning": self.reasoning,
            "blocked": self.blocked,
            "friction_blocked": self.friction_blocked,
            "expected_return_pct": self.expected_return_pct,
        }


@dataclass
class IntradayState:
    date: str
    scans: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date, "scans": self.scans, "trades": self.trades}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntradayState:
        return cls(
            date=str(data.get("date", _today_str())),
            scans=list(data.get("scans") or []),
            trades=list(data.get("trades") or []),
        )


def default_state_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "intraday_state.json"


def load_state(path: Optional[Path] = None) -> IntradayState:
    p = path or default_state_path()
    if not p.exists():
        return IntradayState(date=_today_str())
    data = json.loads(p.read_text(encoding="utf-8"))
    state = IntradayState.from_dict(data)
    if state.date != _today_str():
        return IntradayState(date=_today_str())
    return state


def save_state(state: IntradayState, path: Optional[Path] = None) -> Path:
    p = path or default_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
    tmp = p.with_suffix(".tmp")
    try:
        import fcntl

        lock_file = p.parent / ".intraday.lock"
        with open(lock_file, "w", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(p)
    except (ImportError, OSError):
        p.write_text(payload, encoding="utf-8")
    return p


def reset_state(path: Optional[Path] = None) -> IntradayState:
    state = IntradayState(date=_today_str())
    save_state(state, path)
    return state


def record_scan(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    plugin_names: Optional[list[str]] = None,
    state: Optional[IntradayState] = None,
    state_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Record one intraday data collection (S_n) after experts + evaluate."""
    cfg = settings or load_settings()
    st = state or load_state(state_path)

    if len(st.scans) >= MAX_SCANS:
        raise RuntimeError(f"今日扫描已达上限 {MAX_SCANS} 次（S1-S{MAX_SCANS}）")

    enriched = run_experts(dict(snapshot), cfg, names=plugin_names)
    enriched.setdefault("report_type", "intraday")
    enriched.setdefault("as_of", datetime.now(timezone.utc).isoformat())

    evaluation = evaluate_snapshot(enriched, cfg, doctor_channels=doctor_channels)
    report = evaluation["report"]
    scan_id = f"S{len(st.scans) + 1}"

    entry = {
        "scan_id": scan_id,
        "as_of": report.get("as_of"),
        "code": report.get("code"),
        "name": report.get("name"),
        "mss_final": report.get("mss_final"),
        "mss_breakdown": report.get("mss_breakdown"),
        "verdict": report.get("verdict"),
        "confidence": report.get("confidence"),
        "price": enriched.get("price"),
        "audit_passed": evaluation["audit"].passed,
    }
    st.scans.append(entry)
    save_state(st, state_path)

    lookback_mss, lookback_detail = compute_lookback_mss(st.scans, cfg)
    trend = detect_mss_trend(st.scans)

    return {
        "scan": entry,
        "enriched": enriched,
        "state": st.to_dict(),
        "evaluation": evaluation,
        "lookback_mss": lookback_mss,
        "lookback_detail": lookback_detail,
        "trend": trend,
        "markdown": render_intraday_scan_markdown(entry, lookback_mss, lookback_detail, trend, report),
    }


def should_evaluate_trade(
    state: Optional[IntradayState] = None,
    settings: Optional[dict[str, Any]] = None,
    *,
    state_path: Optional[Path] = None,
) -> bool:
    """Heuristic: trade after ≥3 scans, <5 trades, on trend shift or every 2nd scan."""
    cfg = settings or load_settings()
    sched = cfg.get("schedule", {})
    if not sched.get("intraday_trade_enabled", True):
        return False

    st = state or load_state(state_path)
    if len(st.scans) < int(sched.get("trade_min_scans", 3)):
        return False
    if len(st.trades) >= MAX_TRADES:
        return False

    trend = detect_mss_trend(st.scans)
    if trend in ("turning_up", "turning_down", "rising", "falling"):
        return True
    return len(st.scans) % int(sched.get("trade_every_n_scans", 2)) == 0


def evaluate_trade(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    plugin_names: Optional[list[str]] = None,
    state: Optional[IntradayState] = None,
    state_path: Optional[Path] = None,
    expected_return_pct: Optional[float] = None,
    pre_enriched: Optional[dict[str, Any]] = None,
    pre_evaluation: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate T_n trade opportunity using lookback MSS over recent scans."""
    cfg = settings or load_settings()
    st = state or load_state(state_path)

    if len(st.trades) >= MAX_TRADES:
        raise RuntimeError(f"今日调仓已达上限 {MAX_TRADES} 次（T1-T{MAX_TRADES}）")
    if not st.scans:
        raise RuntimeError("尚无扫描记录，请先运行 daily-run intraday scan")

    if pre_enriched is not None and pre_evaluation is not None:
        enriched = pre_enriched
        evaluation = pre_evaluation
    else:
        enriched = run_experts(dict(snapshot), cfg, names=plugin_names)
        enriched.setdefault("report_type", "intraday")
        evaluation = evaluate_snapshot(enriched, cfg, doctor_channels=doctor_channels)

    report = evaluation["report"]
    verdict = evaluation["verdict"]

    lookback_mss, lookback_detail = compute_lookback_mss(st.scans, cfg)
    trend = detect_mss_trend(st.scans)
    decision = _decide_trade(
        lookback_mss=lookback_mss,
        trend=trend,
        verdict=verdict,
        report=report,
        snapshot=enriched,
        settings=cfg,
        trade_index=len(st.trades) + 1,
        expected_return_pct=expected_return_pct,
    )

    trade_record = {
        **decision.to_dict(),
        "as_of": datetime.now(timezone.utc).isoformat(),
        "verdict": report.get("verdict"),
        "mss_final": report.get("mss_final"),
        "code": report.get("code"),
        "name": report.get("name"),
    }
    st.trades.append(trade_record)
    save_state(st, state_path)

    return {
        "decision": decision.to_dict(),
        "trade": trade_record,
        "state": st.to_dict(),
        "evaluation": evaluation,
        "markdown": render_intraday_trade_markdown(decision, lookback_detail, report, st.scans),
    }


def run_intraday(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    plugin_names: Optional[list[str]] = None,
    push: bool = True,
    trade: bool = False,
    title: Optional[str] = None,
    config=None,
    expected_return_pct: Optional[float] = None,
    state_path: Optional[Path] = None,
) -> dict[str, Any]:
    """One-click intraday: record scan → optional trade eval → Feishu push."""
    cfg = settings or load_settings()
    steps: list[str] = []

    scan_result = record_scan(
        snapshot,
        settings=cfg,
        doctor_channels=doctor_channels,
        plugin_names=plugin_names,
        state_path=state_path,
    )
    steps.append("scan")

    trade_result = None
    do_trade = trade or should_evaluate_trade(
        IntradayState.from_dict(scan_result["state"]), cfg, state_path=state_path
    )
    if do_trade and not trade:
        steps.append("trade_auto")

    if do_trade:
        trade_result = evaluate_trade(
            scan_result.get("enriched") or snapshot,
            settings=cfg,
            doctor_channels=doctor_channels,
            plugin_names=plugin_names,
            state=IntradayState.from_dict(scan_result["state"]),
            state_path=state_path,
            expected_return_pct=expected_return_pct,
            pre_enriched=scan_result.get("enriched"),
            pre_evaluation=scan_result.get("evaluation"),
        )
        steps.append("trade")

    feishu_result = None
    if push:
        from agent_reach.config import Config
        from agent_reach.integrations.feishu import send_card

        cfg_obj = config or Config()
        tpl = cfg.get("report", {}).get("feishu_template_intraday", "blue")
        scan_id = scan_result["scan"]["scan_id"]
        name = scan_result["scan"].get("name") or scan_result["scan"].get("code") or "大盘"
        card_title = title or f"📊 盘中 {scan_id} · {name}"

        md_parts = [scan_result["markdown"]]
        if trade_result:
            md_parts.append("\n---\n\n" + trade_result["markdown"])
        feishu_result = send_card(cfg_obj, card_title, "\n".join(md_parts), template=tpl)
        steps.append("push")

    return {
        "steps": steps,
        "scan": scan_result,
        "trade": trade_result,
        "feishu": feishu_result,
    }


def render_intraday_scan_markdown(
    scan: dict[str, Any],
    lookback_mss: float,
    lookback_detail: list[dict[str, Any]],
    trend: str,
    report: dict[str, Any],
) -> str:
    trend_map = {
        "rising": "上升",
        "falling": "下降",
        "turning_up": "拐点向上",
        "turning_down": "拐点向下",
        "flat": "横盘",
        "mixed": "震荡",
        "insufficient": "数据不足",
    }
    lines = [
        f"**{scan['scan_id']} 数据收集完成**",
        "",
        f"**即时 MSS：** {scan.get('mss_final')} 分 · **标签：** {scan.get('verdict')}",
        f"**Lookback MSS：** {lookback_mss} 分 · **趋势：** {trend_map.get(trend, trend)}",
    ]
    if lookback_detail:
        lines.extend(["", "**Lookback 加权拆解：**"])
        for item in lookback_detail:
            lines.append(
                f"- {item['scan_id']}: MSS {item['mss_final']} × {item['weight']:.0%} "
                f"= {item['weighted']}"
            )
    if report.get("reasoning"):
        lines.extend(["", f"**研判：** {report['reasoning']}"])
    return "\n".join(lines)


def render_intraday_trade_markdown(
    decision: TradeDecision,
    lookback_detail: list[dict[str, Any]],
    report: dict[str, Any],
    scans: list[dict[str, Any]],
) -> str:
    action_map = {"buy": "买入", "sell": "卖出", "hold": "观望", "skip": "跳过"}
    lines = [
        f"**{decision.trade_id or '调仓评估'} · {action_map.get(decision.action, decision.action)}**",
        "",
        f"**Lookback MSS：** {decision.lookback_mss} 分 · **趋势：** {decision.trend}",
        f"**决策：** {decision.reasoning}",
    ]
    if decision.friction_blocked:
        lines.append("⚠️ **摩擦惩罚阻断：** 预期收益不足以覆盖佣金与滑点")
    if decision.blocked:
        lines.append("⚠️ **风控阻断：** 当前不允许执行买入")

    lines.extend(["", "**前序扫描回顾：**"])
    for s in scans[-3:]:
        lines.append(f"- {s['scan_id']}: MSS {s.get('mss_final')} · {s.get('verdict')}")

    if lookback_detail:
        lines.extend(["", "**Lookback 权重计算：**"])
        for item in lookback_detail:
            lines.append(
                f"- {item['scan_id']}: {item['mss_final']} × {item['weight']:.0%} = {item['weighted']}"
            )

    if report.get("invalidation"):
        lines.extend(["", f"**失效条件：** {report['invalidation']}"])
    return "\n".join(lines)


def _decide_trade(
    *,
    lookback_mss: float,
    trend: str,
    verdict: Any,
    report: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    trade_index: int,
    expected_return_pct: Optional[float],
) -> TradeDecision:
    thresholds = settings.get("thresholds", {})
    trading = settings.get("trading", {})
    macro_veto = float(thresholds.get("macro_veto", 40))
    aggressive = float(thresholds.get("aggressive_entry", 50))
    min_cash = float(thresholds.get("min_cash_ratio", 0.4))

    trade_id = f"T{trade_index}"
    portfolio = snapshot.get("portfolio") or {}
    cash_ratio = portfolio.get("cash_ratio")

    exp_ret = expected_return_pct
    if exp_ret is None:
        exp_ret = _estimate_expected_return(lookback_mss, aggressive, macro_veto)

    friction_blocked = not _passes_friction(exp_ret, trading)
    blocked = verdict.blocked or report.get("blocked", False)

    if lookback_mss < macro_veto:
        return TradeDecision(
            action="sell" if not _holding_locked(snapshot, settings) else "hold",
            trade_id=trade_id,
            lookback_mss=lookback_mss,
            lookback_detail=[],
            trend=trend,
            reasoning=f"Lookback MSS {lookback_mss:.0f} 低于否决线 {macro_veto:.0f}，宏观避险",
            blocked=False,
            friction_blocked=False,
            expected_return_pct=exp_ret,
        )

    if blocked:
        return TradeDecision(
            action="hold",
            trade_id=trade_id,
            lookback_mss=lookback_mss,
            lookback_detail=[],
            trend=trend,
            reasoning=f"标签 {verdict.verdict} 阻断买入（即时 MSS {verdict.mss_final:.0f}）",
            blocked=True,
            friction_blocked=friction_blocked,
            expected_return_pct=exp_ret,
        )

    if lookback_mss >= aggressive and trend in ("rising", "turning_up"):
        if cash_ratio is not None and cash_ratio < min_cash:
            return TradeDecision(
                action="hold",
                trade_id=trade_id,
                lookback_mss=lookback_mss,
                lookback_detail=[],
                trend=trend,
                reasoning=f"现金比例 {cash_ratio:.0%} 低于最低 {min_cash:.0%}，暂不加仓",
                blocked=True,
                friction_blocked=friction_blocked,
                expected_return_pct=exp_ret,
            )
        if friction_blocked:
            return TradeDecision(
                action="hold",
                trade_id=trade_id,
                lookback_mss=lookback_mss,
                lookback_detail=[],
                trend=trend,
                reasoning=f"MSS 达 {lookback_mss:.0f} 但预期收益 {exp_ret:.2%} 不足以覆盖摩擦成本",
                blocked=False,
                friction_blocked=True,
                expected_return_pct=exp_ret,
            )
        return TradeDecision(
            action="buy",
            trade_id=trade_id,
            lookback_mss=lookback_mss,
            lookback_detail=[],
            trend=trend,
            reasoning=f"Lookback MSS {lookback_mss:.0f} ≥ {aggressive:.0f} 且趋势 {trend}，条件性建仓",
            blocked=False,
            friction_blocked=False,
            expected_return_pct=exp_ret,
        )

    return TradeDecision(
        action="hold",
        trade_id=trade_id,
        lookback_mss=lookback_mss,
        lookback_detail=[],
        trend=trend,
        reasoning=f"Lookback MSS {lookback_mss:.0f}，趋势 {trend}，维持观望",
        blocked=False,
        friction_blocked=friction_blocked,
        expected_return_pct=exp_ret,
    )


def _passes_friction(expected_return_pct: float, trading: dict[str, Any]) -> bool:
    commission = float(trading.get("commission_rate", 0.0015)) * 2
    slippage = float(trading.get("slippage_rate", 0.001)) * 2
    return expected_return_pct > commission + slippage


def _estimate_expected_return(mss: float, aggressive: float, macro_veto: float) -> float:
    if mss >= aggressive:
        return 0.015 + (mss - aggressive) * 0.001
    if mss <= macro_veto:
        return -0.02
    return 0.005


def _holding_locked(snapshot: dict[str, Any], settings: dict[str, Any]) -> bool:
    lock_days = int(settings.get("trading", {}).get("holding_lock_days", 3))
    holdings = (snapshot.get("portfolio") or {}).get("holdings") or []
    for h in holdings:
        days_held = h.get("days_held")
        if days_held is not None and int(days_held) < lock_days:
            return True
    return False


def _today_str() -> str:
    return date.today().isoformat()
