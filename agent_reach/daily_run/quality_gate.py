# -*- coding: utf-8 -*-
"""Report quality gate before Feishu push."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateResult:
    passed: bool
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    downgraded: bool = False

    def summary(self) -> str:
        if self.passed:
            return "质量门禁通过"
        return "质量门禁未通过：缺少 " + ", ".join(self.missing_fields)


def validate_report(report: dict[str, Any], settings: dict[str, Any]) -> GateResult:
    """Ensure required fields exist before push."""
    gate_cfg = settings.get("quality_gate", {})
    required = gate_cfg.get("required_fields", [])
    missing = [f for f in required if not _has_value(report.get(f))]

    warnings: list[str] = []
    downgraded = False

    if report.get("verdict") == settings.get("verdict_labels", {}).get("buy", "可做"):
        if not _has_value(report.get("entry_price")):
            warnings.append("可做标签但缺少 entry_price")
        if not _has_value(report.get("stop_loss_price")):
            warnings.append("可做标签但缺少 stop_loss_price")

    if missing and gate_cfg.get("allow_downgrade_on_missing_technical"):
        # downgrade verdict in report copy — caller handles
        downgraded = True
        warnings.append("缺少必填字段，建议降级为观察")

    passed = len(missing) == 0
    if not passed and downgraded and gate_cfg.get("block_push_on_fail", True):
        # still block if critical fields missing
        critical = {"verdict", "mss_final", "reasoning", "invalidation"}
        if critical.intersection(missing):
            passed = False
        else:
            passed = True

    return GateResult(
        passed=passed,
        missing_fields=missing,
        warnings=warnings,
        downgraded=downgraded,
    )


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True
