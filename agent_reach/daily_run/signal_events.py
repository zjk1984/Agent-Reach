# -*- coding: utf-8
"""Discrete signal events above MSS verdict (Backtrader Signal-style thin layer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SignalEvent:
    code: str
    name: str
    signal: str
    verdict: str = ""
    mss_final: Optional[float] = None
    macro_veto: Optional[float] = None
    blocked: bool = False
    friction_blocked: bool = False
    team_consensus: str = ""
    source: str = "intraday"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "signal": self.signal,
            "verdict": self.verdict,
            "mss_final": self.mss_final,
            "macro_veto": self.macro_veto,
            "blocked": self.blocked,
            "friction_blocked": self.friction_blocked,
            "team_consensus": self.team_consensus,
            "source": self.source,
            "notes": self.notes[:3],
        }


def signal_events_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return dict((settings or {}).get("signal_events") or {}).get("enabled", True) is not False


def build_signal_event(
    snapshot: dict[str, Any],
    decision: Any,
    *,
    source: str = "intraday",
) -> dict[str, Any]:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    if isinstance(decision, dict):
        action = str(decision.get("action") or "hold")
        blocked = bool(decision.get("blocked"))
        friction_blocked = bool(decision.get("friction_blocked"))
        reasoning = str(decision.get("reasoning") or "")
    else:
        action = str(getattr(decision, "action", None) or "hold")
        blocked = bool(getattr(decision, "blocked", False))
        friction_blocked = bool(getattr(decision, "friction_blocked", False))
        reasoning = str(getattr(decision, "reasoning", "") or "")

    code = _normalize_code(str(snapshot.get("code") or ""))
    review = snapshot.get("team_review") or {}
    notes: list[str] = []
    if reasoning:
        notes.append(reasoning[:80])
    if blocked:
        notes.append("blocked")
    if friction_blocked:
        notes.append("friction_blocked")

    event = SignalEvent(
        code=code,
        name=str(snapshot.get("name") or code),
        signal=action,
        verdict=str(snapshot.get("verdict") or ""),
        mss_final=snapshot.get("mss_final"),
        macro_veto=snapshot.get("macro_veto"),
        blocked=blocked,
        friction_blocked=friction_blocked,
        team_consensus=str(review.get("consensus_label") or snapshot.get("team_consensus_label") or ""),
        source=source,
        notes=notes,
    )
    return event.to_dict()
