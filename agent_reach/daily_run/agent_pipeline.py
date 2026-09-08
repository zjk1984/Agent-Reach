# -*- coding: utf-8
"""Director → Quant → Risk → Execution handoff schema (AutoHedge-inspired)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent_reach.daily_run.snapshot_builder import _normalize_code

PIPELINE_SCHEMA_VERSION = 1

# Prompt templates for LLM stages (deterministic path fills the same fields).
THESIS_PROMPT = """Task: {task}
Stock: {stock}
Market thesis (concise): {thesis}
Key factors: {factors}
"""

QUANT_ANALYSIS_PROMPT = """Stock: {stock}
Thesis from Director: {thesis}

Generate quantitative analysis:
"ticker": str,
"technical_score": float (0-1),
"volume_score": float (0-1),
"trend_strength": float (0-1),
"volatility": float,
"probability_score": float (0-1),
"key_levels": {{"support": float, "resistance": float, "pivot": float}}
"""

RISK_ASSESSMENT_PROMPT = """Stock: {stock}
Thesis: {thesis}
Quant Analysis: {quant_analysis}

Provide risk assessment:
1. Recommended position size
2. Maximum drawdown risk
3. Market risk exposure
4. Overall risk score (0-1)
"""

EXECUTION_INTENT_PROMPT = """Stock: {stock}
Thesis: {thesis}
Risk Assessment: {risk_assessment}

Generate execution intent:
1. action (buy/sell/hold)
2. order_type (market/limit)
3. target_weight_pct
4. stop_loss
5. take_profit
6. time_in_force
"""

_SYMBOL_JSON_RE = re.compile(r"\[[\s\"'0-9A-Za-z,\.]+\]")
_CODE_RE = re.compile(r"\b([036]\d{5})\b")


def shanghai_agent_time_line(*, now: Optional[datetime] = None) -> str:
    ts = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    line = ts.strftime("%A, %B %d, %Y at %H:%M %Z")
    return f"Current date and time (use this as now): {line}"


def llm_system_suffix(*, now: Optional[datetime] = None) -> str:
    return f"\n\n{shanghai_agent_time_line(now=now)}"


def _expert_score_map(snapshot: dict[str, Any]) -> dict[str, float]:
    scores = snapshot.get("expert_scores") or {}
    if isinstance(scores, dict):
        out: dict[str, float] = {}
        for key, val in scores.items():
            try:
                out[str(key)] = float(val)
            except (TypeError, ValueError):
                continue
        return out
    return {}


def build_thesis(snapshot: dict[str, Any], report: dict[str, Any], *, task: str = "") -> dict[str, Any]:
    code = _normalize_code(str(report.get("code") or snapshot.get("code") or ""))
    name = str(report.get("name") or snapshot.get("name") or code)
    factors: list[str] = []
    for key in ("reasoning", "invalidation"):
        text = str(report.get(key) or "").strip()
        if text:
            factors.append(text[:160])
    team = snapshot.get("team_review") or {}
    if team.get("consensus_label"):
        factors.append(f"team={team.get('consensus_label')} score={team.get('consensus_score')}")
    macro = str(snapshot.get("macro_summary") or "").strip()
    if macro:
        factors.append(macro[:120])
    thesis_text = str(report.get("reasoning") or report.get("verdict") or "观察").strip()
    return {
        "code": code,
        "name": name,
        "task": str(task or "").strip()[:240],
        "thesis": thesis_text[:400],
        "verdict": str(report.get("verdict") or ""),
        "confidence": str(report.get("confidence") or ""),
        "mss_final": report.get("mss_final"),
        "blocked": bool(report.get("blocked")),
        "key_factors": factors[:6],
    }


def build_quant_analysis(snapshot: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    scores = _expert_score_map(snapshot)
    breakdown = snapshot.get("mss_breakdown") or {}
    technical = float(scores.get("technical") or breakdown.get("technical") or 50)
    quant = float(scores.get("quant") or breakdown.get("quant") or 50)
    volume = float(breakdown.get("flow") or scores.get("sentiment") or 50)
    mss = float(report.get("mss_final") or snapshot.get("mss_final") or 50)
    return {
        "ticker": _normalize_code(str(report.get("code") or snapshot.get("code") or "")),
        "technical_score": round(technical / 100.0, 3),
        "volume_score": round(volume / 100.0, 3),
        "quant_score": round(quant / 100.0, 3),
        "trend_strength": round(min(1.0, max(0.0, (technical - 40) / 40)), 3),
        "probability_score": round(min(1.0, max(0.0, mss / 100.0)), 3),
        "volatility": snapshot.get("volatility") or snapshot.get("atr_pct"),
        "key_levels": {
            "support": snapshot.get("support") or snapshot.get("ma20"),
            "resistance": snapshot.get("resistance"),
            "pivot": snapshot.get("price") or snapshot.get("last_price"),
        },
        "summary": _expert_summary(snapshot, "quant") or _expert_summary(snapshot, "technical"),
    }


def build_risk_assessment(
    snapshot: dict[str, Any],
    report: dict[str, Any],
    quant: dict[str, Any],
) -> dict[str, Any]:
    scores = _expert_score_map(snapshot)
    risk_score = float(scores.get("risk") or (snapshot.get("mss_breakdown") or {}).get("risk") or 50)
    pf = snapshot.get("portfolio") or {}
    cash_ratio = pf.get("cash_ratio")
    deploy = snapshot.get("deploy_budget") or {}
    max_position = deploy.get("max_position_pct") or snapshot.get("max_position_pct")
    blocked = bool(report.get("blocked"))
    return {
        "recommended_position_pct": None if blocked else max_position,
        "cash_ratio": cash_ratio,
        "risk_score": round(risk_score / 100.0, 3),
        "max_drawdown_risk": "elevated" if risk_score < 45 else "moderate" if risk_score < 60 else "low",
        "market_exposure": "defensive" if float(cash_ratio or 0) > 0.35 else "balanced",
        "blocked": blocked,
        "summary": _expert_summary(snapshot, "risk"),
        "quant_probability": quant.get("probability_score"),
    }


def build_execution_intent(
    snapshot: dict[str, Any],
    report: dict[str, Any],
    risk: dict[str, Any],
    *,
    workflow: str = "morning",
) -> dict[str, Any]:
    verdict = str(report.get("verdict") or "观察")
    blocked = bool(report.get("blocked") or risk.get("blocked"))
    if blocked or verdict in ("回避", "观察"):
        action = "hold"
    elif verdict in ("可做", "买入", "增持"):
        action = "buy"
    elif verdict in ("减仓", "卖出"):
        action = "sell"
    else:
        action = "hold"
    return {
        "action": action,
        "order_type": "limit",
        "target_weight_pct": risk.get("recommended_position_pct"),
        "stop_loss": report.get("stop_loss_price"),
        "take_profit": report.get("entry_price"),
        "time_in_force": "day" if workflow == "intraday" else "gtc",
        "workflow": workflow,
        "verdict": verdict,
        "blocked": blocked,
    }


def build_pipeline_handoff(
    snapshot: dict[str, Any],
    evaluation: dict[str, Any],
    *,
    workflow: str = "morning",
    task: str = "",
) -> dict[str, Any]:
    report = evaluation.get("report") or {}
    thesis = build_thesis(snapshot, report, task=task)
    quant = build_quant_analysis(snapshot, report)
    risk = build_risk_assessment(snapshot, report, quant)
    execution = build_execution_intent(snapshot, report, risk, workflow=workflow)
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "workflow": workflow,
        "code": thesis.get("code"),
        "name": thesis.get("name"),
        "thesis": thesis,
        "quant_analysis": quant,
        "risk_assessment": risk,
        "execution_intent": execution,
    }


def build_expert_agent_trace(
    expert_results: list[dict[str, Any]],
    *,
    workflow: str = "morning",
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for row in expert_results or []:
        if not isinstance(row, dict):
            continue
        trace.append(
            {
                "role": str(row.get("name") or "expert"),
                "workflow": workflow,
                "score": row.get("score"),
                "summary": str(row.get("summary") or "")[:240],
                "success": row.get("success", True),
            }
        )
    return trace


def build_agent_trace(
    snapshot: dict[str, Any],
    evaluation: dict[str, Any],
    *,
    workflow: str = "morning",
) -> list[dict[str, Any]]:
    trace = build_expert_agent_trace(snapshot.get("expert_results") or [], workflow=workflow)
    report = evaluation.get("report") or {}
    trace.append(
        {
            "role": "verdict",
            "workflow": workflow,
            "score": report.get("mss_final"),
            "summary": f"{report.get('verdict')} MSS={report.get('mss_final')}",
            "success": not bool(report.get("blocked")),
        }
    )
    return trace


def _expert_summary(snapshot: dict[str, Any], name: str) -> str:
    for row in snapshot.get("expert_results") or []:
        if isinstance(row, dict) and row.get("name") == name:
            return str(row.get("summary") or "")[:200]
    return ""


def _parse_json_symbol_array(text: str) -> list[str]:
    match = _SYMBOL_JSON_RE.search(text)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0).replace("'", '"'))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        code = _normalize_code(str(item))
        if code.isdigit() and len(code) == 6:
            out.append(code)
    return out


def discover_symbols_from_task(
    task: str,
    *,
    portfolio: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Extract A-share codes from natural-language task (regex + portfolio name match)."""
    del settings  # reserved for future LLM discovery
    text = str(task or "").strip()
    if not text:
        return []

    codes: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        norm = _normalize_code(code)
        if norm.isdigit() and len(norm) == 6 and norm not in seen:
            seen.add(norm)
            codes.append(norm)

    for code in _parse_json_symbol_array(text):
        _add(code)
    for match in _CODE_RE.findall(text):
        _add(match)

    pf = portfolio or {}
    name_index: dict[str, str] = {}
    for row in list(pf.get("holdings") or []) + list(pf.get("watchlist") or []):
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        name = str(row.get("name") or "").strip()
        if code and name:
            name_index[name] = code

    for name, code in name_index.items():
        if name and name in text:
            _add(code)

    return codes
