# -*- coding: utf-8
"""Investment checklist gate — quality-screen + info richness (ai-berkshire inspired)."""

from __future__ import annotations

from typing import Any, Optional


def investment_checklist_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_cfg

    block = dict(berkshire_cfg(settings).get("investment_checklist") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "block_buy_on_fail": block.get("block_buy_on_fail", True) is not False,
        "require_quality_pass": block.get("require_quality_pass", True) is not False,
        "require_richness_above_c": block.get("require_richness_above_c", True) is not False,
    }


def evaluate_investment_checklist(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    audit: Any | None = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled
    from agent_reach.daily_run.berkshire.info_richness import grade_info_richness
    from agent_reach.daily_run.berkshire.quality_screen import screen_from_snapshot

    cfg = investment_checklist_cfg(settings)
    if not berkshire_enabled(settings, key="investment_checklist") or not cfg.get("enabled", True):
        return {"passed": True, "skipped": True, "reasons": []}

    reasons: list[str] = []
    richness = grade_info_richness(snapshot, audit=audit)
    quality = screen_from_snapshot(snapshot)

    if cfg.get("require_richness_above_c") and richness.get("grade") == "C":
        reasons.append(f"信息{richness.get('grade')}级：{richness.get('note')}")
    if cfg.get("require_quality_pass") and not quality.passed and "数据不足" not in quality.reason:
        reasons.append(f"quality-screen：{quality.reason}")

    passed = len(reasons) == 0
    block_buy = bool(cfg.get("block_buy_on_fail") and not passed)
    return {
        "passed": passed,
        "block_buy": block_buy,
        "richness": richness,
        "quality": quality.to_dict(),
        "reasons": reasons,
    }


def apply_checklist_to_verdict_downgrade(
    downgrade: list[str],
    *,
    checklist: dict[str, Any],
) -> None:
    if checklist.get("skipped") or checklist.get("passed"):
        return
    for reason in checklist.get("reasons") or []:
        if reason not in downgrade:
            downgrade.append(f"investment-checklist：{reason}")
