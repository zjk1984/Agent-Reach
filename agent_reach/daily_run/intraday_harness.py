# -*- coding: utf-8
"""Intraday scan / trade findings → harness self-evolution."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.harness_skill_base import apply_skill_refinement
from agent_reach.daily_run.portfolio_manager import trade_buy_budget_blocked


def _decision_buy_budget_blocked(decision: dict[str, Any]) -> bool:
    """Decision-layer deploy budget precheck — not a failed trade apply."""
    return trade_buy_budget_blocked(decision)


def _profit_lock_context(
    payload: dict[str, Any],
    *,
    scan_block: dict[str, Any],
    scan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Optional[dict[str, Any]], str]:
    enriched = scan_block.get("enriched") or payload.get("enriched") or payload.get("snapshot") or {}
    snapshot = dict(enriched)
    snapshot.setdefault("code", scan.get("code") or payload.get("code"))
    snapshot.setdefault("name", scan.get("name") or payload.get("name"))

    state = scan_block.get("state") if isinstance(scan_block, dict) else {}
    if not isinstance(state, dict):
        state = payload.get("state") or {}
    session_scans = list(state.get("scans") or payload.get("scans") or [])
    prior_trades = list(state.get("trades") or payload.get("trades") or [])

    trade = payload.get("trade")
    decision = None
    if isinstance(trade, dict):
        decision = trade.get("decision") or trade

    scan_id = str(scan.get("scan_id") or payload.get("scan_id") or "S?")
    return snapshot, session_scans, prior_trades, decision if isinstance(decision, dict) else None, scan_id


def _append_profit_lock_harness_evidence(
    memory: list[str],
    policy: list[str],
    playbook: list[str],
    *,
    settings: Optional[dict[str, Any]],
    payload: dict[str, Any],
    scan_block: dict[str, Any],
    scan: dict[str, Any],
) -> None:
    if not settings:
        return
    from agent_reach.daily_run.profit_lock import profit_lock_harness_evidence

    snapshot, session_scans, prior_trades, decision, scan_id = _profit_lock_context(
        payload,
        scan_block=scan_block,
        scan=scan,
    )
    code = str(snapshot.get("code") or scan.get("code") or "")
    name = str(snapshot.get("name") or scan.get("name") or code or "标的")
    if not code:
        return
    lines = profit_lock_harness_evidence(
        settings,
        code=code,
        name=name,
        scan_id=scan_id,
        snapshot=snapshot,
        decision=decision,
        prior_trades=prior_trades,
        session_scans=session_scans,
    )
    memory.extend(lines.get("memory") or [])
    policy.extend(lines.get("policy") or [])
    playbook.extend(lines.get("playbook") or [])


def intraday_to_harness_evidence(
    payload: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    memory: list[str] = []
    policy: list[str] = []
    playbook: list[str] = []
    plan: list[str] = []

    scan_block = payload.get("scan") or payload
    scan = scan_block.get("scan") if isinstance(scan_block, dict) and "scan" in scan_block else scan_block
    if not isinstance(scan, dict):
        scan = {}

    state = scan_block.get("state") if isinstance(scan_block, dict) else {}
    if isinstance(state, dict):
        scans = state.get("scans") or []
    else:
        scans = payload.get("scans") or []

    scan_id = scan.get("scan_id") or f"S{len(scans)}"
    name = scan.get("name") or scan.get("code") or "标的"
    mss = scan.get("mss_final")
    trend = scan_block.get("trend") or payload.get("trend")
    lookback = scan_block.get("lookback_mss") or payload.get("lookback_mss")

    if mss is not None:
        memory.append(f"盘中 {scan_id} {name} MSS={mss} trend={trend or '—'}")
    verdict_reason = str(scan.get("verdict_reasoning") or scan.get("reasoning") or "")
    if "达进攻阈值" in verdict_reason:
        playbook.append(f"盘中 {scan_id} {name} MSS 达进攻阈值（harness aggressive_entry 进化项）")
    if lookback is not None:
        memory.append(f"Lookback MSS={float(lookback):.0f}（{scan_id}）")

    scan_count = len(scans) if scans else payload.get("scan_count")
    if scan_count is not None:
        if int(scan_count) < 3:
            memory.append("盘中扫描偏少：intraday 次数不足，下日 trade_min_scans 可降至 2")
            plan.append(f"intraday：{name} 扫描仅 {scan_count} 次，确认 cron S3–S12")
        elif int(scan_count) >= 13:
            playbook.append(f"盘中扫描充足（{scan_count} 次），Lookback 权重可信")

    source = scan.get("source")
    if source and source != "morning" and scan_id == "S2":
        memory.append("S2 未标记 morning 来源")
        plan.append("morning：08:00 全量早盘应写入 record_morning_scan(source=morning)")

    trade = payload.get("trade")
    if isinstance(trade, dict):
        decision = trade.get("decision") or trade
        if isinstance(decision, dict):
            action = decision.get("action")
            reasoning = str(decision.get("reasoning") or "")
            trend_label = str(decision.get("trend") or trend or "")
            if action and action != "hold":
                playbook.append(f"盘中 {scan_id} {action}：{reasoning[:120]}")
            if decision.get("friction_blocked"):
                memory.append("减少频繁调仓：摩擦成本过高时提高 friction_min_return_pct")
                policy.append("摩擦成本过高：提高 exp_return 门槛或 friction_min_return_pct")
            portfolio_msg = str(trade.get("portfolio_message") or "")
            if "落账已达上限" in portfolio_msg or "落账已达上限" in reasoning:
                memory.append(
                    "落账已达上限：全组合 paper apply 次数过多，下日收紧 max_applied_trades_per_day"
                )
            if "评估已达上限" in reasoning:
                memory.append(
                    "评估已达上限：单标的 T 槽不足，下日放宽 max_trade_evaluations_per_symbol"
                )
            if (
                "达进攻阈值" in reasoning
                and action in (None, "hold", "skip")
                and not _decision_buy_budget_blocked(decision)
            ):
                memory.append(
                    "达进攻阈值未落账：MSS 达标但未成交，下日检查 trade_min_scans/落账上限/friction"
                )
                policy.append("达进攻阈值未落账：放宽 trend_delta 或降低 exp_return 门槛")
            if decision.get("blocked") and "macro" in reasoning.lower():
                memory.append("宏观一票否决生效：维持高现金，禁止接飞刀")
            if action == "hold" and trend_label in ("mixed", "flat") and float(lookback or 0) >= 50:
                policy.append("趋势误判：mixed/flat 时 MSS 达标但未买入，收紧 buy_trends")
            if action == "buy" and trend_label == "turning_up" and decision.get("friction_blocked"):
                policy.append("过早买入：turning_up 摩擦阻断，提高 trend_min_points")
            if "Kronos 偏弱" in reasoning:
                policy.append(f"Kronos 偏弱阻断买入：{name}({scan.get('code') or '?'})")
            if "Kronos 偏强" in reasoning or (
                action == "buy" and "条件性建仓" in reasoning and "≥" in reasoning
            ):
                playbook.append(f"Kronos 偏多放宽进攻阈值：{name}({scan.get('code') or '?'})")
            if (
                ("最低部署" in portfolio_msg or "可部署现金" in portfolio_msg)
                and not _decision_buy_budget_blocked(decision)
            ):
                policy.append("可部署现金不足：提高 min_deploy_cash 或降低 deploy_ratio")
            if "数据审计未通过" in reasoning or "行情覆盖率不足" in reasoning:
                policy.append("数据审计未通过：盘中 block_on_audit_fail 生效")
                plan.append(f"intraday：补全 {name} 行情/flow/sentiment 后再调仓")
            if action == "sell" and "防御性减仓" in reasoning:
                policy.append("防御性减仓：defensive_trim 触发卖出")
            if action == "hold" and "防御性减仓" in reasoning:
                policy.append("卖晚了：防御信号触发但深度套牢/锁仓阻断")

    _append_profit_lock_harness_evidence(
        memory,
        policy,
        playbook,
        settings=settings,
        payload=payload,
        scan_block=scan_block if isinstance(scan_block, dict) else {},
        scan=scan,
    )

    if settings:
        from agent_reach.daily_run.technical_scenario_watch import (
            evaluate_active_scenarios,
            maybe_register_upper_shadow_from_session,
            technical_scenario_harness_evidence,
        )

        snapshot, session_scans, _prior, _decision, _scan_id = _profit_lock_context(
            payload,
            scan_block=scan_block if isinstance(scan_block, dict) else {},
            scan=scan,
        )
        code = str(snapshot.get("code") or scan.get("code") or "")
        name = str(snapshot.get("name") or scan.get("name") or code)
        if code:
            maybe_register_upper_shadow_from_session(
                code=code,
                name=name,
                snapshot=snapshot,
                session_scans=session_scans,
                settings=settings,
            )
            evals = evaluate_active_scenarios(snapshot, settings=settings)
            lines = technical_scenario_harness_evidence(evals, settings=settings)
            memory.extend(lines.get("memory") or [])
            policy.extend(lines.get("policy") or [])
            playbook.extend(lines.get("playbook") or [])
            plan.extend(lines.get("plan") or [])

    if payload.get("skipped"):
        reason = str(payload.get("reason") or "")
        memory.append(f"intraday skipped：{reason}")
        if "上限" in reason or "MAX" in reason.upper():
            plan.append("intraday：扫描达上限，确认 S12 是否落在 15:00")

    for row in payload.get("symbol_results") or []:
        if row.get("skipped"):
            continue
        inner = row.get("result") or {}
        scan_block = inner.get("scan") or {}
        scan_inner = scan_block.get("scan") if isinstance(scan_block, dict) else {}
        if not isinstance(scan_inner, dict):
            scan_inner = scan_block if isinstance(scan_block, dict) else {}
        sub_payload = {
            "code": row.get("code"),
            "name": row.get("name"),
            "trade": inner.get("trade"),
            "scan": scan_block,
        }
        _append_profit_lock_harness_evidence(
            memory,
            policy,
            playbook,
            settings=settings,
            payload=sub_payload,
            scan_block=scan_block if isinstance(scan_block, dict) else {},
            scan=scan_inner,
        )
        if settings:
            from agent_reach.daily_run.technical_scenario_watch import (
                evaluate_active_scenarios,
                maybe_register_upper_shadow_from_session,
                technical_scenario_harness_evidence,
            )

            snapshot, session_scans, _prior, _decision, _sid = _profit_lock_context(
                sub_payload,
                scan_block=scan_block if isinstance(scan_block, dict) else {},
                scan=scan_inner,
            )
            code = str(snapshot.get("code") or row.get("code") or "")
            name = str(snapshot.get("name") or row.get("name") or code)
            if code:
                maybe_register_upper_shadow_from_session(
                    code=code,
                    name=name,
                    snapshot=snapshot,
                    session_scans=session_scans,
                    settings=settings,
                )
            evals = evaluate_active_scenarios(snapshot, settings=settings)
            lines = technical_scenario_harness_evidence(evals, settings=settings)
            memory.extend(lines.get("memory") or [])
            policy.extend(lines.get("policy") or [])
            playbook.extend(lines.get("playbook") or [])
            plan.extend(lines.get("plan") or [])

    summary = f"intraday {scan_id} {name} scans={scan_count}"
    return {
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "summary": summary,
    }


def apply_intraday_harness_refinement(
    payload: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    evidence = intraday_to_harness_evidence(payload, settings=settings)
    if not any(evidence.get(k) for k in ("memory", "policy", "playbook", "plan")):
        return {"skipped": True, "reason": "empty evidence", "job": "intraday"}
    result = apply_skill_refinement("intraday", evidence, settings=settings)
    enriched = payload.get("enriched") or payload.get("snapshot") or {}
    if enriched.get("expert_results") or enriched.get("team_review"):
        from agent_reach.daily_run.expert_consensus_harness import apply_expert_consensus_harness_refinement

        expert = apply_expert_consensus_harness_refinement(
            enriched,
            settings=settings,
            workflow="intraday",
        )
        if not expert.get("skipped"):
            result["expert_consensus"] = expert
    return result
