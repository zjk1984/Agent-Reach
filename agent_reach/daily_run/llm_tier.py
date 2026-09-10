# -*- coding: utf-8
"""Quick/deep and tool/reasoning LLM tier resolution (TradingAgents + DeepEar-style)."""

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

_DEFAULT_JOB_ROLES: dict[str, str] = {
    "morning": "tool",
    "intraday": "tool",
    "close": "tool",
    "code_walk": "tool",
    "counter_thesis_llm": "tool",
    "weekly": "reasoning",
    "forecast": "reasoning",
    "decision_reflection": "reasoning",
    "risk_debate": "reasoning",
    "invest_debate": "reasoning",
}

_DEFAULT_ROLE_TIERS: dict[str, str] = {
    "tool": "tool",
    "reasoning": "reasoning",
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
    if not root.get("tool"):
        root.setdefault("tool", dict(root.get("quick") or {}))
    if not root.get("reasoning"):
        root.setdefault("reasoning", dict(root.get("deep") or {}))
    return root


def llm_tier_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = llm_tier_cfg(settings)
    return cfg.get("enabled", True) is not False


def resolve_job_role(job: str, settings: Optional[dict[str, Any]] = None) -> str:
    cfg = llm_tier_cfg(settings)
    job_roles = dict(cfg.get("job_roles") or {})
    role = str(job_roles.get(job) or _DEFAULT_JOB_ROLES.get(job) or "tool").strip().lower()
    return role if role in ("tool", "reasoning") else "tool"


def resolve_job_tier(job: str, settings: Optional[dict[str, Any]] = None) -> str:
    cfg = llm_tier_cfg(settings)
    job_tiers = dict(cfg.get("job_tiers") or {})
    explicit = job_tiers.get(job)
    if explicit:
        tier = str(explicit).strip().lower()
        if tier in ("quick", "deep", "tool", "reasoning"):
            return tier
    role = resolve_job_role(job, settings)
    role_tiers = dict(cfg.get("role_tiers") or _DEFAULT_ROLE_TIERS)
    tier = str(role_tiers.get(role) or _DEFAULT_JOB_TIERS.get(job) or "quick").strip().lower()
    if tier in ("tool", "reasoning"):
        return tier
    if tier in ("quick", "deep"):
        return tier
    return "quick"


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
    out["llm_role"] = resolve_job_role(job, settings)
    return out
