# -*- coding: utf-8
"""Nested decision layers — Strategy / Scan / Execution (Qlib NestedExecutor inspired)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def nested_decision_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("nested_decision") or {})
    layers = block.get("layers") or ["signal", "risk", "execution"]
    if isinstance(layers, str):
        layers = [s.strip() for s in layers.split(",") if s.strip()]
    return {
        "enabled": block.get("enabled", True) is not False,
        "layers": tuple(str(x) for x in layers),
        "persist_in_trade": block.get("persist_in_trade", True) is not False,
    }


@dataclass
class DecisionLayer:
    name: str
    verdict: str
    blocked: bool = False
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "blocked": self.blocked,
            "reason": self.reason,
            "meta": dict(self.meta),
        }


def build_nested_decision(
    *,
    signal_verdict: str,
    signal_blocked: bool,
    signal_reason: str,
    risk_verdict: str,
    risk_blocked: bool,
    risk_reason: str,
    execution_action: str,
    execution_blocked: bool,
    execution_reason: str,
    settings: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = nested_decision_cfg(settings)
    if not cfg["enabled"]:
        return {"enabled": False, "layers": []}

    layer_map = {
        "signal": DecisionLayer(
            "signal",
            signal_verdict,
            blocked=signal_blocked,
            reason=signal_reason,
            meta={"lookback_mss": (extra or {}).get("lookback_mss")},
        ),
        "risk": DecisionLayer(
            "risk",
            risk_verdict,
            blocked=risk_blocked,
            reason=risk_reason,
            meta={
                "block_kind": (extra or {}).get("block_kind"),
                "protection": (extra or {}).get("protection"),
            },
        ),
        "execution": DecisionLayer(
            "execution",
            execution_action,
            blocked=execution_blocked,
            reason=execution_reason,
            meta={
                "friction_blocked": (extra or {}).get("friction_blocked"),
                "fill_timing": (extra or {}).get("fill_timing"),
            },
        ),
    }
    layers = [layer_map[name].to_dict() for name in cfg["layers"] if name in layer_map]
    final_blocked = any(layer["blocked"] for layer in layers)
    return {
        "enabled": True,
        "layers": layers,
        "final_action": execution_action if not final_blocked else "hold",
        "final_blocked": final_blocked,
    }


def attach_nested_decision_to_trade(
    trade_record: dict[str, Any],
    decision: Any,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = nested_decision_cfg(settings)
    if not cfg["enabled"] or not cfg["persist_in_trade"]:
        return trade_record

    action = str(getattr(decision, "action", None) or trade_record.get("action") or "hold")
    blocked = bool(getattr(decision, "blocked", False) or trade_record.get("blocked"))
    block_kind = getattr(decision, "block_kind", None) or trade_record.get("block_kind")
    reasoning = str(getattr(decision, "reasoning", None) or trade_record.get("reasoning") or "")

    signal_blocked = bool(getattr(decision, "friction_blocked", False))
    risk_blocked = blocked and block_kind not in {None, "buy_budget", "protection_buy", "protection_sell"}
    if block_kind and str(block_kind).startswith("protection"):
        risk_blocked = True

    nested = build_nested_decision(
        signal_verdict=str(trade_record.get("verdict") or "—"),
        signal_blocked=signal_blocked,
        signal_reason="friction" if signal_blocked else "",
        risk_verdict="blocked" if risk_blocked else "pass",
        risk_blocked=risk_blocked,
        risk_reason=str(block_kind or "") if risk_blocked else "",
        execution_action=action,
        execution_blocked=blocked,
        execution_reason=reasoning[:160],
        settings=settings,
        extra={
            "lookback_mss": getattr(decision, "lookback_mss", None),
            "block_kind": block_kind,
            "friction_blocked": getattr(decision, "friction_blocked", False),
        },
    )
    trade_record["nested_decision"] = nested
    if not trade_record.get("evaluation"):
        trade_record["evaluation"] = {}
    trade_record["evaluation"]["nested_decision"] = nested
    return trade_record


def render_nested_decision_markdown(nested: dict[str, Any]) -> str:
    if not nested or not nested.get("enabled"):
        return ""
    lines = ["### Nested Decision", ""]
    for layer in nested.get("layers") or []:
        flag = "🚫" if layer.get("blocked") else "✅"
        lines.append(
            f"- {flag} **{layer.get('name')}** → {layer.get('verdict')} "
            f"{('· ' + str(layer.get('reason'))) if layer.get('reason') else ''}"
        )
    return "\n".join(lines)
