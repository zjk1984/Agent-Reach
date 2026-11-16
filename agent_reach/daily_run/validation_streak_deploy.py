# -*- coding: utf-8
"""Weekly forecast validation streak → conservative deploy cap (AR-29 / phase C)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.forecast_validation_harness import validation_harness_cfg


def validation_streak_deploy_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = validation_harness_cfg(settings)
    raw = dict((settings or {}).get("week_forecast") or {})
    block = dict(raw.get("validation_harness") or {})
    return {
        **base,
        "deploy_step_per_week": float(block.get("deploy_step_per_week", 0.05)),
        "deploy_floor": float(block.get("deploy_floor", 0.15)),
        "deploy_release_step_per_week": float(block.get("deploy_release_step_per_week", 0.05)),
    }


def validation_streak_deploy_state_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "harness" / "validation_streak_deploy.json"


def load_validation_streak_deploy_state() -> dict[str, Any]:
    path = validation_streak_deploy_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_validation_streak_deploy_state(state: dict[str, Any]) -> Path:
    path = validation_streak_deploy_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _base_deploy_ratio(settings: dict[str, Any]) -> float:
    from agent_reach.daily_run.harness_policy import resolve_harness_base_position_policy

    base = resolve_harness_base_position_policy(settings)
    return max(0.05, min(1.0, float(base.get("deploy_ratio", 1.0))))


def streak_penalty_weeks(signal: dict[str, Any], cfg: dict[str, Any]) -> int:
    if not signal.get("active"):
        return 0
    index_streak = int(signal.get("index_miss_streak") or 0)
    bench_streak = int(signal.get("benchmark_underperform_week_streak") or 0)
    excess = 0
    if index_streak >= cfg["index_miss_streak_warn"]:
        excess = max(excess, index_streak - cfg["index_miss_streak_warn"] + 1)
    if bench_streak >= cfg["benchmark_underperform_streak_warn"]:
        excess = max(excess, bench_streak - cfg["benchmark_underperform_streak_warn"] + 1)
    return max(0, excess)


def compute_validation_streak_deploy_cap(
    signal: dict[str, Any],
    *,
    settings: dict[str, Any],
    prior_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Target deploy cap from streak signal; gradual release when streak clears."""
    cfg = validation_streak_deploy_cfg(settings)
    base = _base_deploy_ratio(settings)
    state = dict(prior_state or load_validation_streak_deploy_state())
    prev_cap = float(state.get("deploy_cap", base))
    penalty = streak_penalty_weeks(signal, cfg)

    if penalty > 0:
        target = max(cfg["deploy_floor"], base - cfg["deploy_step_per_week"] * penalty)
        target = min(base, target)
        active = True
    else:
        if prev_cap < base - 1e-6:
            target = min(base, prev_cap + cfg["deploy_release_step_per_week"])
        else:
            target = base
        active = target < base - 1e-6

    return {
        "deploy_cap": round(target, 4),
        "base_deploy": round(base, 4),
        "deploy_cap_before": round(prev_cap, 4),
        "penalty_weeks": penalty,
        "overlay_active": active,
        "signal_active": bool(signal.get("active")),
    }


def apply_validation_streak_deploy_to_merged(
    merged: dict[str, float],
    *,
    settings: dict[str, Any],
) -> dict[str, float]:
    """Runtime overlay path: cap deploy_ratio only (does not touch cash floors / gate)."""
    cfg = validation_streak_deploy_cfg(settings)
    if not cfg.get("auto_tighten_deploy_on_streak"):
        return merged
    state = load_validation_streak_deploy_state()
    cap = state.get("deploy_cap")
    if cap is None or not state.get("overlay_active"):
        return merged
    eff = min(float(merged.get("deploy_ratio", 1.0)), float(cap))
    if abs(eff - float(merged.get("deploy_ratio", 1.0))) >= 0.001:
        merged["deploy_ratio"] = eff
    return merged


def render_deploy_tighten_feishu_line(apply: dict[str, Any]) -> str:
    if not apply.get("changed"):
        return ""
    before = apply.get("deploy_cap_before")
    after = apply.get("deploy_cap")
    if before is None or after is None:
        return ""
    reasons = "；".join(apply.get("reasons") or []) or "预测校验 streak"
    return (
        f"📉 {reasons}：deploy 上限 {float(before):.0%}→{float(after):.0%} "
        f"（floor {float(apply.get('deploy_floor', 0.15)):.0%}，现金护栏未绕过）"
    )


def maybe_apply_validation_streak_deploy_tighten(
    record: dict[str, Any],
    signal: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist deploy cap + apply_audit when auto_tighten enabled and cap moves."""
    cfg = validation_streak_deploy_cfg(settings)
    if not cfg.get("auto_tighten_deploy_on_streak"):
        return {"skipped": True, "reason": "auto_tighten disabled"}

    settings = dict(settings or {})
    computed = compute_validation_streak_deploy_cap(signal, settings=settings)
    before = float(computed["deploy_cap_before"])
    after = float(computed["deploy_cap"])
    changed = abs(after - before) >= 0.001

    state = {
        "schema": "validation_streak_deploy_v1",
        "week_start": record.get("week_start"),
        "week_end": record.get("week_end"),
        "deploy_cap": after,
        "base_deploy": computed["base_deploy"],
        "deploy_cap_before": before,
        "penalty_weeks": computed["penalty_weeks"],
        "overlay_active": computed["overlay_active"],
        "signal_active": computed["signal_active"],
        "index_miss_streak": signal.get("index_miss_streak"),
        "benchmark_underperform_week_streak": signal.get("benchmark_underperform_week_streak"),
        "reasons": list(signal.get("reasons") or []),
        "deploy_floor": cfg["deploy_floor"],
    }
    save_validation_streak_deploy_state(state)

    audit: dict[str, Any] = {}
    if changed:
        from agent_reach.daily_run.harness_apply_gate import record_apply_audit

        audit = record_apply_audit(
            job="weekly",
            status="applied",
            reason="validation_streak_deploy_tighten",
            layer="a",
            changes=1,
            injection_meta={"validation_streak_deploy": state},
        )

    apply = {
        "changed": changed,
        "skipped": False,
        "deploy_cap": after,
        "deploy_cap_before": before,
        "deploy_floor": cfg["deploy_floor"],
        "overlay_active": computed["overlay_active"],
        "reasons": state["reasons"],
        "apply_audit_at": audit.get("at"),
        "feishu_line": render_deploy_tighten_feishu_line(
            {
                "changed": changed,
                "deploy_cap_before": before,
                "deploy_cap": after,
                "deploy_floor": cfg["deploy_floor"],
                "reasons": state["reasons"],
            }
        ),
    }
    if signal.get("active") and cfg.get("auto_tighten_deploy_on_streak"):
        signal["apply"] = True
        signal["deploy_cap"] = after
        signal["note"] = (
            f"auto_tighten: deploy_cap {before:.0%}→{after:.0%}"
            if changed
            else f"auto_tighten: deploy_cap held at {after:.0%}"
        )
    return apply