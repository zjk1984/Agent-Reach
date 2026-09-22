# -*- coding: utf-8
"""Pluggable decision model (jev-trader Model interface for daily-run)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class DecisionResult:
    action: str  # buy | sell | hold
    probabilities: dict[str, float]
    latency_ms: float
    input_tokens: int = 0
    reasoning: str = ""


class DecisionModel(Protocol):
    name: str

    def decide(self, state: dict[str, Any]) -> DecisionResult: ...


class MockDecisionModel:
    """Deterministic MSS heuristic for CI (jev MockModel pattern)."""

    name = "mock"

    def decide(self, state: dict[str, Any]) -> DecisionResult:
        mss = float(state.get("mss_final") or state.get("lookback_mss") or 50)
        veto = float(state.get("macro_veto") or 40)
        aggressive = float(state.get("aggressive_entry") or 50)
        if mss >= aggressive:
            action = "buy"
            buy_p = min(0.95, 0.5 + (mss - aggressive) / 40)
        elif mss < veto:
            action = "sell"
            buy_p = max(0.05, 0.5 - (veto - mss) / 40)
        else:
            action = "hold"
            buy_p = 0.5
        sell_p = 1.0 - buy_p if action != "hold" else 0.25
        hold_p = max(0.0, 1.0 - buy_p - sell_p)
        return DecisionResult(
            action=action,
            probabilities={"buy": buy_p, "sell": sell_p, "hold": hold_p},
            latency_ms=1.0,
            input_tokens=0,
            reasoning=f"mock mss={mss:.1f} veto={veto} agg={aggressive}",
        )


class RuleDecisionModel:
    """Pass-through: daily-run uses existing _decide_trade; this wraps state for tests."""

    name = "rule"

    def decide(self, state: dict[str, Any]) -> DecisionResult:
        action = str(state.get("action") or "hold")
        return DecisionResult(
            action=action,
            probabilities={"buy": 0.33, "sell": 0.33, "hold": 0.34},
            latency_ms=0.0,
            reasoning="rule passthrough",
        )


def create_decision_model(settings: Optional[dict[str, Any]] = None) -> DecisionModel:
    backend = str(((settings or {}).get("decision_model") or {}).get("backend") or "rule").strip().lower()
    if backend == "mock":
        return MockDecisionModel()
    return RuleDecisionModel()
