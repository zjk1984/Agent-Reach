# -*- coding: utf-8
"""DeepSeek optimizer for rejected_strategies.weekly_whatif thresholds."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.rejected_whatif_policy import (
    _WEEKLY_WHATIF_BOUNDS,
    _WEEKLY_WHATIF_KEYS,
    _clamp_policy,
    format_weekly_whatif_policy_line,
    weekly_whatif_policy_base,
)


def _section_cfg(settings: Optional[dict[str, Any]]) -> dict[str, Any]:
    root = dict((settings or {}).get("harness_evolution") or {})
    sec = dict((settings or {}).get("rejected_strategies") or {}).get("weekly_whatif") or {}
    if isinstance(sec, dict):
        sec = dict(sec)
    else:
        sec = {}
    llm_refine = dict((settings or {}).get("harness") or {}).get("llm_refine") or {}
    sell_cfg = dict((settings or {}).get("sell_rules_whatif") or {})
    if root.get("llm_optimize") is False or sec.get("llm_optimize") is False:
        return {"llm_optimize": False}
    provider = str(
        sec.get("llm_provider")
        or root.get("llm_provider")
        or sell_cfg.get("llm_provider")
        or llm_refine.get("provider")
        or "deepseek"
    )
    return {
        "llm_optimize": sec.get("llm_optimize", root.get("llm_optimize", True)),
        "llm_provider": provider,
        "llm_model": sec.get("llm_model") or root.get("llm_model") or llm_refine.get("model"),
        "llm_timeout_seconds": int(
            sec.get("llm_timeout_seconds")
            or root.get("llm_timeout_seconds")
            or llm_refine.get("timeout_seconds")
            or 45
        ),
        "llm_temperature": float(sec.get("llm_temperature") or root.get("llm_temperature") or 0.1),
    }


def build_weekly_whatif_optimize_payload(
    report: dict[str, Any],
    *,
    refresh_result: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.skill_rejected import _candidates_from_weekly_report

    refresh = refresh_result or {}
    candidates = _candidates_from_weekly_report(report, settings)
    return {
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "weekly_pnl_pct": report.get("weekly_pnl_pct"),
        "refresh": {
            "added": refresh.get("added") or [],
            "archived": refresh.get("archived"),
        },
        "candidate_titles": [title for title, _ in candidates],
        "current": weekly_whatif_policy_base(settings),
        "constraints": {k: list(v) for k, v in _WEEKLY_WHATIF_BOUNDS.items()},
        "objective": (
            "根据证伪库 weekly refresh 入库/漏检与 what-if 候选，"
            "给出下一周 rejected weekly_whatif 阈值最优解；"
            "盈利周误入库则抬高门槛，亏损周漏检则适度降低"
        ),
    }


def optimize_weekly_whatif_with_deepseek(
    report: dict[str, Any],
    *,
    refresh_result: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = _section_cfg(settings)
    if not cfg.get("llm_optimize"):
        return {"skipped": True, "reason": "rejected_strategies.weekly_whatif.llm_optimize disabled"}

    from agent_reach.daily_run.llm_chat import chat_json, resolve_chat_provider

    provider = str(cfg.get("llm_provider") or "deepseek")
    if not resolve_chat_provider(provider):
        return {"skipped": True, "reason": "no llm provider (set DEEPSEEK_API_KEY)"}

    import json

    payload = build_weekly_whatif_optimize_payload(
        report,
        refresh_result=refresh_result,
        settings=settings,
    )
    from agent_reach.daily_run.storage.readers import attach_optimizer_storage_context

    payload = attach_optimizer_storage_context(payload, settings=settings, job="rejected_whatif")
    result = chat_json(
        system=(
            "你是 daily-run 证伪库 weekly_whatif 阈值优化器。输出 JSON："
            '{"buy_notional_delta_cny":5000,"sell_pnl_delta_cny":200,'
            '"friction_pass_min":2,"trend_mismatch_min":2,"intraday_sell_missed_min":2,'
            '"deep_loss_lag_count_min":1,"deep_loss_share_delta_min":100,'
            '"sell_threshold_missed_min":2,"forecast_divergence_days_min":3,'
            '"optimizer_score_delta_min":0.05,"kronos_blocked_signals_min":2,'
            '"rationale":"中文理由","confidence":0.0-1.0}。'
            "规则：1) 各字段在 constraints 内；2) 盈利周误入库抬高门槛；"
            "3) 亏损周漏检适度降低；4) rationale 一句话。"
        ),
        user=json.dumps(payload, ensure_ascii=False),
        provider=provider,
        model=cfg.get("llm_model") or None,
        temperature=float(cfg.get("llm_temperature") or 0.1),
        timeout=int(cfg.get("llm_timeout_seconds") or 45),
        max_tokens=640,
    )
    if not isinstance(result, dict):
        return {"skipped": True, "reason": "llm returned no json"}

    ratios = _clamp_policy({key: result.get(key) for key in _WEEKLY_WHATIF_KEYS})
    if len(ratios) < len(_WEEKLY_WHATIF_KEYS):
        return {"skipped": True, "reason": "llm ratios incomplete", "raw": result}

    rationale = str(result.get("rationale") or "").strip()
    policy_line = format_weekly_whatif_policy_line(ratios, rationale=rationale)
    evidence = {
        "memory": [
            (
                "DeepSeek 证伪库 weekly_whatif 最优："
                f"buyΔ={ratios['buy_notional_delta_cny']:.0f} "
                f"sellΔ={ratios['sell_pnl_delta_cny']:.0f} "
                f"friction={ratios['friction_pass_min']:.0f}"
            )
        ],
        "policy": [policy_line] if policy_line else [],
        "playbook": ["DeepSeek rejected weekly_whatif 最优解已写入 harness policy"],
        "plan": ["weekly：验证证伪库 auto-add 与 what-if 阈值对齐"],
        "summary": f"rejected_whatif_llm buyΔ={ratios['buy_notional_delta_cny']:.0f}",
        "llm_optimal": {**ratios, "rationale": rationale},
    }
    return {
        "skipped": False,
        "planner": "deepseek",
        "provider": provider,
        "optimal": ratios,
        "evidence": evidence,
        "raw": result,
    }
