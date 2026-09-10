# -*- coding: utf-8
"""Quick/deep LLM tier resolution (TradingAgents-style model routing)."""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_JOB_TIERS: dict[str, str] = {
    "morning": "quick",
    "intraday": "quick",
    "close": "quick",
    "code_walk": "quick",
    "counter_thesis_llm": "quick",
    "weekly": "deep",
    "forecast": "deep",
    "decision_reflection": "deep",
    "risk_debate": "deep",
    "invest_debate": "deep",
}


def llm_tier_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = dict((settings or {}).get("llm_tier") or {})
    narrative = dict((settings or {}).get("llm_narrative") or {})
    if not root.get("quick") and narrative.get("model"):
        root.setdefault(
            "quick",
            {"provider": narrative.get("provider"), "model": narrative.get("model")},
        )
    if not root.get("deep") and narrative.get("model"):
        root.setdefault(
            "deep",
            {"provider": narrative.get("provider"), "model": narrative.get("model")},
        )
    return root


def llm_tier_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = llm_tier_cfg(settings)
    return cfg.get("enabled", True) is not False


def resolve_job_tier(job: str, settings: Optional[dict[str, Any]] = None) -> str:
    cfg = llm_tier_cfg(settings)
    job_tiers = dict(cfg.get("job_tiers") or {})
    tier = str(job_tiers.get(job) or _DEFAULT_JOB_TIERS.get(job) or "quick").strip().lower()
    return tier if tier in ("quick", "deep") else "quick"


def apply_llm_tier(
    base: dict[str, Any],
    job: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge tier provider/model into an LLM config dict when tier routing is enabled."""
    out = dict(base)
    if not llm_tier_enabled(settings):
        return out
    tier = resolve_job_tier(job, settings)
    tier_cfg = dict((llm_tier_cfg(settings).get(tier) or {}))
    if tier_cfg.get("provider"):
        out["provider"] = tier_cfg["provider"]
    if tier_cfg.get("model"):
        out["model"] = tier_cfg["model"]
    if tier_cfg.get("timeout_seconds"):
        out["timeout_seconds"] = tier_cfg["timeout_seconds"]
    if tier_cfg.get("max_output_tokens"):
        out["max_output_tokens"] = tier_cfg["max_output_tokens"]
    out["llm_tier"] = tier
    return out
