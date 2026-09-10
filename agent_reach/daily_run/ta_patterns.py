# -*- coding: utf-8
"""TradingAgents-inspired patterns: reflection, risk debate, invest debate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run.ta_patterns")


def _block_cfg(settings: Optional[dict[str, Any]], name: str) -> dict[str, Any]:
    return dict((settings or {}).get(name) or {})


def reflection_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = _block_cfg(settings, "decision_reflection")
    if cfg.get("enabled") is False:
        return False
    return True


def risk_debate_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = _block_cfg(settings, "risk_debate")
    if cfg.get("enabled") is False:
        return False
    return True


def invest_debate_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = _block_cfg(settings, "invest_debate")
    if cfg.get("enabled") is False:
        return False
    return True


def build_close_reflection_context(
    *,
    snapshot: dict[str, Any],
    verify: dict[str, Any],
    portfolio_summary: Optional[dict[str, Any]] = None,
    forecast_review: Optional[dict[str, Any]] = None,
    team_review: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    pf = portfolio_summary or {}
    fr = forecast_review or {}
    review = team_review or snapshot.get("team_review") or {}
    return {
        "job": "decision_reflection",
        "scope": "close",
        "code": snapshot.get("code"),
        "name": snapshot.get("name"),
        "verdict": verify.get("verdict_current"),
        "mss_delta": verify.get("mss_delta"),
        "daily_pnl": pf.get("daily_pnl"),
        "daily_pnl_pct": pf.get("daily_pnl_pct"),
        "realized_pnl": pf.get("realized_pnl"),
        "team_consensus_label": review.get("consensus_label") or snapshot.get("team_consensus_label"),
        "team_conflicts": list(review.get("conflicts") or [])[:3],
        "forecast_accuracy": fr.get("accuracy") if isinstance(fr, dict) else None,
        "forecast_symbol_hits": fr.get("symbol_hits") if isinstance(fr, dict) else None,
        "forecast_symbol_total": fr.get("symbol_total") if isinstance(fr, dict) else None,
    }


def build_forecast_reflection_context(forecast: dict[str, Any]) -> dict[str, Any]:
    symbols = forecast.get("symbols") or {}
    kronos_bullish = 0
    kronos_bearish = 0
    for sym in symbols.values():
        if not isinstance(sym, dict):
            continue
        cum = (sym.get("kronos") or {}).get("cum_change_pct")
        if cum is None:
            continue
        if float(cum) >= 0.5:
            kronos_bullish += 1
        elif float(cum) <= -0.5:
            kronos_bearish += 1
    return {
        "job": "decision_reflection",
        "scope": "forecast",
        "week_start": forecast.get("week_start"),
        "week_end": forecast.get("week_end"),
        "symbol_count": len(symbols),
        "kronos_bullish": kronos_bullish,
        "kronos_bearish": kronos_bearish,
        "notes": (forecast.get("notes") or [])[:3],
    }


def build_weekly_reflection_context(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "job": "decision_reflection",
        "scope": "weekly",
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "weekly_pnl": report.get("weekly_pnl"),
        "weekly_pnl_pct": report.get("weekly_pnl_pct"),
        "stock_pnl": report.get("stock_pnl"),
        "cash_pnl": report.get("cash_pnl"),
        "cash_ratio": report.get("cash_ratio"),
        "hot_sectors": (report.get("hot_sectors") or [])[:5],
        "process_improvements": [
            str(i.get("title") or "")[:60] for i in (report.get("process_improvements") or [])[:3]
        ],
    }


def _reflection_deterministic(ctx: dict[str, Any]) -> dict[str, Any]:
    scope = str(ctx.get("scope") or "close")
    focus: list[str] = []
    if scope == "weekly":
        pct = ctx.get("weekly_pnl_pct")
        pnl = ctx.get("weekly_pnl")
        if pnl is not None:
            sign = "+" if float(pnl) >= 0 else ""
            pct_s = f"（{float(pct):+.2f}%）" if pct is not None else ""
            focus.append(f"本周盈亏 {sign}¥{float(pnl):,.0f}{pct_s}")
        for sector in ctx.get("hot_sectors") or []:
            if isinstance(sector, dict):
                focus.append(f"主线 {sector.get('name') or sector.get('sector')}")
            else:
                focus.append(str(sector)[:48])
            if len(focus) >= 3:
                break
        summary = f"周度反思 · {ctx.get('week_start')}~{ctx.get('week_end')}"
    elif scope == "forecast":
        count = ctx.get("symbol_count")
        if count is not None:
            focus.append(f"覆盖 {count} 只标的")
        bull = ctx.get("kronos_bullish")
        bear = ctx.get("kronos_bearish")
        if bull or bear:
            focus.append(f"Kronos 偏多 {bull or 0} / 偏空 {bear or 0}")
        for note in ctx.get("notes") or []:
            focus.append(str(note)[:72])
            if len(focus) >= 3:
                break
        summary = f"预测反思 · {ctx.get('week_start')}~{ctx.get('week_end')}"
    else:
        pnl = ctx.get("daily_pnl")
        pct = ctx.get("daily_pnl_pct")
        if pnl is not None:
            sign = "+" if float(pnl) >= 0 else ""
            pct_s = f"（{float(pct):+.2f}%）" if pct is not None else ""
            focus.append(f"当日盈亏 {sign}¥{float(pnl):,.0f}{pct_s}")
        if ctx.get("verdict"):
            focus.append(f"verify {ctx.get('verdict')}")
        acc = ctx.get("forecast_accuracy")
        if acc is not None:
            focus.append(f"预测准确度 {acc}")
        summary = f"收盘反思 · {ctx.get('name') or ctx.get('code') or '组合'}"
    return {
        "summary": summary,
        "focus_points": focus[:3] or ["维持 MSS 与 macro_veto 纪律"],
        "divergence_notes": [],
        "risk_alerts": [],
        "reflection_prose": "",
        "planner": "deterministic",
    }


def generate_decision_reflection(
    context: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.report_narrative import _generate_narrative

    if not reflection_enabled(settings):
        return {"skipped": True, "reason": "decision_reflection disabled", "job": "decision_reflection"}

    hint = (
        "基于已给盈亏/verify/预测命中写 2-4 句决策反思；"
        "reflection_prose 字段放完整 prose；禁止新增价格或仓位数字。"
    )
    out = _generate_narrative(
        "decision_reflection",
        context,
        settings=settings,
        system=hint,
        deterministic_fn=_reflection_deterministic,
    )
    if not out.get("reflection_prose") and out.get("summary"):
        out["reflection_prose"] = str(out.get("summary") or "")
        for item in out.get("focus_points") or []:
            out["reflection_prose"] += f" {item}"
        out["reflection_prose"] = str(out["reflection_prose"]).strip()[:320]
    return out


def persist_decision_reflection(
    reflection: dict[str, Any],
    *,
    job_scope: str,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append reflection prose to experience jsonl + experience_latest fragment."""
    if reflection.get("skipped"):
        return {"skipped": True, "reason": reflection.get("reason") or "skipped"}
    prose = str(reflection.get("reflection_prose") or reflection.get("summary") or "").strip()
    if not prose:
        return {"skipped": True, "reason": "empty reflection"}

    cfg = _block_cfg(settings, "decision_reflection")
    if cfg.get("persist_experience") is False:
        return {"skipped": True, "reason": "persist disabled", "prose": prose}

    from agent_reach.daily_run.experience import experience_dir

    out_dir = experience_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "experience.jsonl"
    entry = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "decision_reflection",
        "scope": job_scope,
        "planner": reflection.get("planner"),
        "prose": prose[:400],
        "focus_points": list(reflection.get("focus_points") or [])[:3],
    }
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    fragment_path = Path.home() / ".agent-reach" / "daily_run" / "skill" / "experience_latest.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = f"\n\n### 决策反思 ({job_scope} · {stamp})\n\n{prose}\n"
    try:
        fragment_path.parent.mkdir(parents=True, exist_ok=True)
        existing = fragment_path.read_text(encoding="utf-8") if fragment_path.exists() else ""
        fragment_path.write_text((existing.rstrip() + block).lstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("decision_reflection fragment write failed: {}", exc)
        return {"skipped": True, "reason": str(exc), "jsonl": str(jsonl_path)}

    return {"ok": True, "jsonl": str(jsonl_path), "fragment": str(fragment_path)}


def build_risk_debate_context(snapshot: dict[str, Any]) -> Optional[dict[str, Any]]:
    review = snapshot.get("team_review") or {}
    conflicts = list(review.get("conflicts") or [])
    if not conflicts:
        return None
    scores = snapshot.get("expert_scores") or {}
    by_name = {r.get("name"): r for r in (snapshot.get("expert_results") or []) if r.get("name")}
    return {
        "job": "risk_debate",
        "conflicts": conflicts[:4],
        "consensus_label": review.get("consensus_label") or snapshot.get("team_consensus_label"),
        "consensus_score": review.get("consensus_score") or snapshot.get("team_consensus_score"),
        "aggressive_lane": {
            "technical": (by_name.get("technical") or {}).get("score"),
            "quant": (by_name.get("quant") or {}).get("score"),
        },
        "conservative_lane": {"risk": (by_name.get("risk") or {}).get("score")},
        "neutral_lane": {"macro": (by_name.get("macro") or {}).get("score")},
        "expert_scores": scores,
        "counter_thesis": review.get("counter_thesis") or "",
    }


def _risk_debate_deterministic(ctx: dict[str, Any]) -> dict[str, Any]:
    focus = [
        f"激进视角 tech/quant：{ctx.get('aggressive_lane')}",
        f"保守视角 risk：{ctx.get('conservative_lane')}",
        f"中性视角 macro：{ctx.get('neutral_lane')}",
    ]
    for conflict in ctx.get("conflicts") or []:
        focus.append(str(conflict)[:72])
        if len(focus) >= 4:
            break
    return {
        "summary": f"三角风控辩论 · {len(ctx.get('conflicts') or [])} 项冲突",
        "focus_points": focus[:4],
        "divergence_notes": list(ctx.get("conflicts") or [])[:2],
        "risk_alerts": [],
        "planner": "deterministic",
    }


def generate_risk_debate_narrative(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    context = build_risk_debate_context(snapshot)
    if context is None:
        return {"skipped": True, "reason": "no team conflicts", "job": "risk_debate"}
    if not risk_debate_enabled(settings):
        return {"skipped": True, "reason": "risk_debate disabled", "job": "risk_debate"}

    from agent_reach.daily_run.report_narrative import _generate_narrative

    return _generate_narrative(
        "risk_debate",
        context,
        settings=settings,
        system="解读 aggressive/conservative/neutral 三视角与已有 conflicts；不得新增 MSS 或仓位数字。",
        deterministic_fn=_risk_debate_deterministic,
    )


def _invest_debate_checkpoint(scope_key: str, settings: Optional[dict[str, Any]] = None):
    from agent_reach.daily_run.job_checkpoint import JobCheckpoint

    return JobCheckpoint.for_job("invest_debate", scope_key, settings=settings)


def build_weekly_invest_debate_context(report: dict[str, Any]) -> dict[str, Any]:
    sectors = []
    for row in (report.get("hot_sectors") or [])[:5]:
        if isinstance(row, dict):
            sectors.append(
                {
                    "name": row.get("name") or row.get("sector"),
                    "reason": (row.get("reason") or row.get("detail") or "")[:120],
                }
            )
        else:
            sectors.append({"name": str(row)[:48], "reason": ""})
    return {
        "job": "invest_debate",
        "scope": "weekly",
        "scope_key": f"{report.get('week_start')}_{report.get('week_end')}",
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "weekly_pnl_pct": report.get("weekly_pnl_pct"),
        "hot_sectors": sectors,
        "notes": (report.get("notes") or [])[:3],
    }


def build_forecast_invest_debate_context(forecast: dict[str, Any]) -> dict[str, Any]:
    symbols = []
    for code, sym in (forecast.get("symbols") or {}).items():
        if not isinstance(sym, dict):
            continue
        kronos = sym.get("kronos") or {}
        symbols.append(
            {
                "code": code,
                "name": sym.get("name") or code,
                "kronos_cum_pct": kronos.get("cum_change_pct"),
            }
        )
    return {
        "job": "invest_debate",
        "scope": "forecast",
        "scope_key": f"{forecast.get('week_start')}_{forecast.get('week_end')}",
        "week_start": forecast.get("week_start"),
        "week_end": forecast.get("week_end"),
        "symbols": symbols[:8],
        "notes": (forecast.get("notes") or [])[:3],
    }


def _invest_debate_deterministic(ctx: dict[str, Any]) -> dict[str, Any]:
    bull: list[str] = []
    bear: list[str] = []
    for sym in ctx.get("symbols") or []:
        cum = sym.get("kronos_cum_pct")
        name = sym.get("name") or sym.get("code")
        if cum is not None and float(cum) >= 0.5:
            bull.append(f"{name} Kronos {float(cum):+.1f}%")
        elif cum is not None and float(cum) <= -0.5:
            bear.append(f"{name} Kronos {float(cum):+.1f}%")
    for sec in ctx.get("hot_sectors") or []:
        bull.append(f"主线 {sec.get('name')}: {sec.get('reason', '')[:48]}")
        if len(bull) >= 3:
            break
    pct = ctx.get("weekly_pnl_pct")
    if pct is not None and float(pct) < -0.3:
        bear.append(f"本周组合 {float(pct):+.2f}%，偏防守")
    return {
        "summary": f"多空辩论 · {ctx.get('scope')} {ctx.get('week_start')}~{ctx.get('week_end')}",
        "focus_points": (bull[:2] + bear[:2]) or ["暂无明确多空分歧"],
        "divergence_notes": bear[:2],
        "risk_alerts": [],
        "bull_points": bull[:3],
        "bear_points": bear[:3],
        "planner": "deterministic",
    }


def generate_invest_debate_narrative(
    context: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not invest_debate_enabled(settings):
        return {"skipped": True, "reason": "invest_debate disabled", "job": "invest_debate"}

    cfg = _block_cfg(settings, "invest_debate")
    scope_key = str(context.get("scope_key") or context.get("scope") or "default")
    checkpoint = _invest_debate_checkpoint(scope_key, settings)
    checkpoint_data: dict[str, Any] = checkpoint.load() if cfg.get("checkpoint", True) else {}

    from agent_reach.daily_run.report_narrative import _generate_narrative

    rounds = max(1, int(cfg.get("max_rounds", 2)))
    merged = dict(context)
    if checkpoint_data.get("bull_points"):
        merged["prior_bull"] = checkpoint_data.get("bull_points")
    if checkpoint_data.get("bear_points"):
        merged["prior_bear"] = checkpoint_data.get("bear_points")
    merged["debate_rounds"] = rounds

    out = _generate_narrative(
        "invest_debate",
        merged,
        settings=settings,
        system=(
            f"模拟 {rounds} 轮 Bull/Bear 后 Research Manager 收束；"
            "bull_points/bear_points 仅来自输入；禁止新增涨跌幅或目标价。"
        ),
        deterministic_fn=_invest_debate_deterministic,
    )

    if cfg.get("checkpoint", True) and not out.get("skipped"):
        try:
            checkpoint.save(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "scope_key": scope_key,
                    "bull_points": out.get("bull_points") or out.get("focus_points"),
                    "bear_points": out.get("divergence_notes") or [],
                    "summary": out.get("summary"),
                }
            )
        except OSError as exc:
            logger.warning("invest_debate checkpoint write failed: {}", exc)

    return out
