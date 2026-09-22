# -*- coding: utf-8
"""Decision trace: jev-trader-style decision → intent → apply event chain."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai

_LATE_SCAN_TOTALS: dict[str, int] = {}


def decision_trace_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("decision_trace") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "jsonl_dir": str(raw.get("jsonl_dir") or "~/.agent-reach/daily_run/logs"),
        "ring_buffer_scans": max(10, int(raw.get("ring_buffer_scans", 60))),
        "include_probabilities": raw.get("include_probabilities", False) is True,
        "llm_usd_per_mtok": float(raw.get("llm_usd_per_mtok", 0.14)),
    }


def decision_trace_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return decision_trace_cfg(settings)["enabled"]


def trace_jsonl_path(
    settings: Optional[dict[str, Any]] = None,
    *,
    day: Optional[str] = None,
) -> Path:
    cfg = decision_trace_cfg(settings)
    override = os.environ.get("AGENT_REACH_DECISION_TRACE_DIR", "").strip()
    base = Path(override or cfg["jsonl_dir"]).expanduser()
    if os.environ.get("PYTEST_CURRENT_TEST") and not override:
        base = Path(os.environ.get("TMPDIR", "/tmp")) / "agent-reach-decision-trace"
    d = day or today_shanghai().isoformat()
    return base / f"decision_trace-{d}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_allowed_actions(
    *,
    decision_action: str,
    blocked: bool,
    settings: Optional[dict[str, Any]] = None,
    code: Optional[str] = None,
    snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Explicit allowed set for LLM / audit (jev ``allowed: {buy, sell}``)."""
    action = str(decision_action or "hold").lower()
    allowed = {
        "buy": action == "buy" and not blocked,
        "sell": action == "sell" and not blocked,
        "hold": True,
    }
    reason = ""
    if blocked:
        reason = "decision_blocked"
    elif code and snapshot and action == "buy":
        try:
            from agent_reach.daily_run.portfolio_manager import simulate_buy_analysis

            pf = snapshot.get("portfolio") or {}
            enriched = {code: {"code": code, "price": snapshot.get("price"), "name": snapshot.get("name")}}
            sim = simulate_buy_analysis(pf, enriched, settings or {}, prefer_code=code)
            if not sim.get("allowed"):
                allowed["buy"] = False
                reason = str(sim.get("block_reason") or "guard")
        except Exception:
            pass
    return {"buy": allowed["buy"], "sell": allowed["sell"], "hold": allowed["hold"], "reason": reason}


def build_decision_state(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    scans: list[dict[str, Any]],
    lookback_mss: float,
    trend: str,
    settings: Optional[dict[str, Any]] = None,
    horizon_scans: int = 3,
) -> dict[str, Any]:
    """Compact relative features for audit / future structured LLM."""
    prices: list[float] = []
    for scan in scans[-horizon_scans:]:
        p = scan.get("price")
        if p is not None:
            try:
                prices.append(float(p))
            except (TypeError, ValueError):
                pass
    if not prices:
        p = snapshot.get("price") or report.get("price")
        if p is not None:
            try:
                prices.append(float(p))
            except (TypeError, ValueError):
                pass

    returns_bps: dict[str, Optional[float]] = {"last1": None, "last3": None}
    if len(prices) >= 2 and prices[-2]:
        returns_bps["last1"] = round((prices[-1] / prices[-2] - 1) * 10_000, 2)
    if len(prices) >= 2 and prices[0]:
        returns_bps["last3"] = round((prices[-1] / prices[0] - 1) * 10_000, 2)

    mss_vals = [float(s.get("mss_final", 0)) for s in scans[-horizon_scans:] if s.get("mss_final") is not None]
    mss_delta = round(mss_vals[-1] - mss_vals[0], 2) if len(mss_vals) >= 2 else 0.0

    code = str(report.get("code") or snapshot.get("code") or "")
    return {
        "horizon_scans": horizon_scans,
        "returns_bps": returns_bps,
        "mss_delta": mss_delta,
        "trend": trend,
        "recent_prices": " ".join(f"{p:.4f}" for p in prices[-5:]),
        "code": code,
    }


@dataclass
class DecisionEvent:
    event_id: str
    ts: str
    job: str
    scan_id: str
    code: str
    name: str
    price: Optional[float]
    change_pct: Optional[float]
    mss_final: Optional[float]
    lookback_mss: Optional[float]
    trend: str
    allowed: dict[str, Any]
    decision: dict[str, Any]
    intent: Optional[dict[str, Any]]
    apply: Optional[dict[str, Any]]
    totals: dict[str, Any] = field(default_factory=dict)
    late: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "job": self.job,
            "scan_id": self.scan_id,
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "change_pct": self.change_pct,
            "mss_final": self.mss_final,
            "lookback_mss": self.lookback_mss,
            "trend": self.trend,
            "allowed": self.allowed,
            "decision": self.decision,
            "intent": self.intent,
            "apply": self.apply,
            "totals": self.totals,
            "late": self.late,
            "context": self.context,
        }


def _guard_capped(model_action: str, apply: Optional[dict[str, Any]]) -> bool:
    if not apply:
        return False
    model = str(model_action or "hold").lower()
    if model not in ("buy", "sell"):
        return False
    if apply.get("applied"):
        return False
    return True


def build_event_from_trade_eval(
    *,
    job: str,
    scan_id: str,
    report: dict[str, Any],
    snapshot: dict[str, Any],
    decision: Any,
    apply_result: Any,
    lookback_mss: float,
    trend: str,
    scans: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
    latency_ms: Optional[float] = None,
) -> DecisionEvent:
    from agent_reach.daily_run.intraday import TradeDecision, infer_trade_block_kind

    if isinstance(decision, TradeDecision):
        d_action = decision.action
        d_blocked = decision.blocked
        d_reasoning = decision.reasoning or ""
        model_action = decision.action
    else:
        d_action = str(decision.get("action") or "hold")
        d_blocked = bool(decision.get("blocked"))
        d_reasoning = str(decision.get("reasoning") or "")
        model_action = d_action

    code = str(report.get("code") or snapshot.get("code") or "")
    name = str(report.get("name") or code)
    price_raw = snapshot.get("price") or report.get("price")
    try:
        price = float(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price = None
    try:
        change_pct = float(snapshot.get("change_pct")) if snapshot.get("change_pct") is not None else None
    except (TypeError, ValueError):
        change_pct = None

    allowed = build_allowed_actions(
        decision_action=d_action,
        blocked=d_blocked,
        settings=settings,
        code=code,
        snapshot=snapshot,
    )
    context = build_decision_state(
        snapshot=snapshot,
        report=report,
        scans=scans,
        lookback_mss=lookback_mss,
        trend=trend,
        settings=settings,
    )

    apply_dict = apply_result.to_dict() if hasattr(apply_result, "to_dict") else dict(apply_result or {})
    applied = bool(apply_dict.get("applied"))
    guard_capped = _guard_capped(model_action, apply_dict)

    intent: Optional[dict[str, Any]] = None
    if d_action in ("buy", "sell") and not d_blocked:
        intent = {
            "side": d_action,
            "status": "proposed",
            "price": price,
        }
        actions = apply_dict.get("actions") or []
        if actions:
            first = actions[0] if isinstance(actions[0], dict) else {}
            intent["shares"] = first.get("shares")
            intent["amount"] = first.get("amount")

    apply_payload = {
        "status": "filled" if applied else ("blocked" if guard_capped or d_blocked else "hold"),
        "applied": applied,
        "message": apply_dict.get("message") or "",
        "guard_capped": guard_capped,
        "model_action": model_action,
        "applied_action": d_action if applied else "hold",
        "block_kind": infer_trade_block_kind(decision if isinstance(decision, TradeDecision) else decision),
    }

    day = today_shanghai().isoformat()
    event_id = f"{day}:{scan_id}:{code}:{uuid.uuid4().hex[:8]}"

    return DecisionEvent(
        event_id=event_id,
        ts=_now_iso(),
        job=job,
        scan_id=scan_id,
        code=code,
        name=name,
        price=price,
        change_pct=change_pct,
        mss_final=report.get("mss_final"),
        lookback_mss=lookback_mss,
        trend=trend,
        allowed=allowed,
        decision={
            "action": d_action,
            "verdict": report.get("verdict"),
            "blocked": d_blocked,
            "reasoning": d_reasoning[:500] if d_reasoning else "",
            "latency_ms": latency_ms,
        },
        intent=intent,
        apply=apply_payload,
        totals=daily_trace_totals(settings, day=day),
        context=context,
    )


def build_late_scan_event(
    *,
    job: str,
    scan_id: str,
    code: str,
    name: str,
    reason: str,
    settings: Optional[dict[str, Any]] = None,
) -> DecisionEvent:
    day = today_shanghai().isoformat()
    _LATE_SCAN_TOTALS[day] = _LATE_SCAN_TOTALS.get(day, 0) + 1
    return DecisionEvent(
        event_id=f"{day}:{scan_id}:{code}:late:{uuid.uuid4().hex[:8]}",
        ts=_now_iso(),
        job=job,
        scan_id=scan_id,
        code=code,
        name=name,
        price=None,
        change_pct=None,
        mss_final=None,
        lookback_mss=None,
        trend="insufficient",
        allowed={"buy": False, "sell": False, "hold": True, "reason": "late_scan"},
        decision={"action": "hold", "verdict": None, "blocked": False, "reasoning": reason, "latency_ms": None},
        intent=None,
        apply={"status": "hold", "applied": False, "message": reason, "guard_capped": False},
        totals=daily_trace_totals(settings, day=day),
        late=True,
    )


def append_decision_event(
    event: DecisionEvent | dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    if not decision_trace_enabled(settings):
        return None
    record = event.to_dict() if isinstance(event, DecisionEvent) else dict(event)
    path = trace_jsonl_path(settings)
    from agent_reach.daily_run.jsonl_log import append_jsonl_capped

    append_jsonl_capped(path, record)
    return path


def daily_trace_totals(
    settings: Optional[dict[str, Any]] = None,
    *,
    day: Optional[str] = None,
) -> dict[str, Any]:
    d = day or today_shanghai().isoformat()
    late = _LATE_SCAN_TOTALS.get(d, 0)
    path = trace_jsonl_path(settings, day=d)
    events = 0
    trades = 0
    llm_usd = 0.0
    late_from_file = 0
    if path.is_file():
        try:
            import json

            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                events += 1
                row = json.loads(line)
                if row.get("late"):
                    late_from_file += 1
                apply = row.get("apply") or {}
                if apply.get("applied"):
                    trades += 1
                dec = row.get("decision") or {}
                tokens = dec.get("input_tokens") or 0
                if tokens:
                    llm_usd += (float(tokens) / 1_000_000) * decision_trace_cfg(settings)["llm_usd_per_mtok"]
        except (OSError, ValueError):
            pass
    late = max(late, late_from_file)
    return {
        "late_scans": late,
        "day_events": events,
        "day_trades": trades,
        "llm_usd_estimate": round(llm_usd, 6),
    }


def render_decision_trace_markdown(event: DecisionEvent | dict[str, Any]) -> str:
    """Feishu snippet: intent vs apply (jev quote.capped style)."""
    data = event.to_dict() if isinstance(event, DecisionEvent) else dict(event)
    if data.get("late"):
        return (
            f"⏭ **late_scan** · {data.get('scan_id')} · {data.get('name')} ({data.get('code')})\n"
            f"- {data.get('apply', {}).get('message') or data.get('decision', {}).get('reasoning')}"
        )

    dec = data.get("decision") or {}
    apply = data.get("apply") or {}
    intent = data.get("intent") or {}
    scan_id = data.get("scan_id", "")
    name = data.get("name") or data.get("code")
    code = data.get("code", "")
    model_action = apply.get("model_action") or dec.get("action") or "hold"
    lines = [f"### 🧭 Decision Trace · {scan_id} · {name} ({code})"]

    verdict = dec.get("verdict")
    mss = data.get("mss_final")
    if mss is not None:
        lines.append(f"- **MSS** {mss} · **verdict** {verdict or '—'} · **趋势** {data.get('trend')}")

    if intent.get("status") == "proposed":
        side = intent.get("side", model_action)
        price = intent.get("price")
        shares = intent.get("shares")
        price_s = f" @ ¥{price:.2f}" if price is not None else ""
        share_s = f" {shares}股" if shares else ""
        lines.append(f"- **intent** ⏳ 拟{side}{share_s}{price_s}")

    status = apply.get("status") or "hold"
    if apply.get("applied"):
        lines.append(f"- **apply** ✅ 已成交 — {apply.get('message') or ''}".strip())
    elif apply.get("guard_capped"):
        lines.append(
            f"- **apply** 🛡 guard_capped — 模型 **{model_action}**，实际 **{apply.get('applied_action', 'hold')}**"
        )
        if apply.get("message"):
            lines.append(f"  - {apply['message'][:200]}")
    elif status == "blocked":
        lines.append(f"- **apply** ⛔ 阻断 — {apply.get('message') or dec.get('reasoning', '')[:200]}")
    else:
        lines.append(f"- **apply** ⏸ hold")

    totals = data.get("totals") or {}
    if totals.get("late_scans"):
        lines.append(f"- 今日 late_scans: {totals['late_scans']}")
    return "\n".join(lines)


def render_daily_llm_cost_line(
    *,
    settings: Optional[dict[str, Any]] = None,
    day: Optional[str] = None,
    daily_pnl: Optional[float] = None,
) -> str:
    totals = daily_trace_totals(settings, day=day)
    llm = float(totals.get("llm_usd_estimate") or 0)
    if llm <= 0 and daily_pnl is None:
        return ""
    parts = [f"LLM 估算成本 ${llm:.4f}"]
    if daily_pnl is not None:
        parts.append(f"当日盈亏 ¥{daily_pnl:+,.0f}")
        if llm > 0 and daily_pnl:
            ratio = abs(llm * 7.2 / daily_pnl) if daily_pnl else 0
            parts.append(f"成本/盈亏比 {ratio:.2%}")
    return " · ".join(parts)
