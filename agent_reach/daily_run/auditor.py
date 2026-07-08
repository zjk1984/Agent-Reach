# -*- coding: utf-8 -*-
"""Data authenticity audit before analysis or trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class AuditResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structured_review_complete: bool = True

    def summary(self) -> str:
        if self.passed:
            return "数据审计通过"
        return "数据审计未通过：" + "；".join(self.issues)


def run_data_audit(
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    *,
    doctor_channels: Optional[dict[str, dict]] = None,
) -> AuditResult:
    """Validate snapshot freshness, sources, price anchors, and doctor readiness."""
    audit_cfg = settings.get("data_audit", {})
    thresholds = settings.get("thresholds", {})
    issues: list[str] = []
    warnings: list[str] = []
    structured_review_complete = True

    as_of_raw = snapshot.get("as_of")
    if not as_of_raw:
        issues.append("缺少 as_of 时间戳")
    else:
        try:
            as_of = _parse_dt(as_of_raw)
            age_hours = (datetime.now(timezone.utc) - as_of).total_seconds() / 3600
            max_age = float(thresholds.get("max_snapshot_age_hours", 24))
            if age_hours < -0.1:
                issues.append("as_of 时间戳在未来")
            elif age_hours > max_age:
                issues.append(f"数据过期（{age_hours:.1f}h > {max_age}h）")
        except ValueError as exc:
            issues.append(str(exc))

    required_cats = audit_cfg.get("required_source_categories", [])
    sources = snapshot.get("sources") or {}
    if isinstance(sources, dict):
        present = set(sources.keys())
    elif isinstance(sources, list):
        present = set(sources)
    else:
        present = set()
        issues.append("sources 格式无效")

    missing_cats = [c for c in required_cats if c not in present]
    if missing_cats:
        issues.append(f"缺少数据来源类别：{', '.join(missing_cats)}")
        if "quote" in missing_cats:
            structured_review_complete = False

    for cat in required_cats:
        if cat in present and isinstance(sources, dict):
            if not sources.get(cat):
                warnings.append(f"来源类别 {cat} 为空")

    ref_price = snapshot.get("reference_price")
    live_price = snapshot.get("price")
    if ref_price is not None and live_price is not None:
        try:
            ref = float(ref_price)
            live = float(live_price)
            if ref > 0:
                dev = abs(live - ref) / ref
                max_dev = float(thresholds.get("max_price_deviation_pct", 0.08))
                if dev > max_dev:
                    msg = f"价格锚点偏差 {dev:.1%} 超过阈值 {max_dev:.1%}"
                    if audit_cfg.get("block_on_price_deviation", True):
                        issues.append(msg)
                    else:
                        warnings.append(msg)
        except (TypeError, ValueError):
            issues.append("reference_price 或 price 无法解析为数字")

    code = snapshot.get("code")
    name = snapshot.get("name")
    if code and name:
        code_str = str(code).strip()
        if code_str not in str(name) and str(name) not in code_str:
            # loose check — warn only unless explicit mismatch flag
            if snapshot.get("identity_mismatch"):
                issues.append(f"标的身份不一致：{code} vs {name}")

    if doctor_channels and audit_cfg.get("required_doctor_channels"):
        for ch in audit_cfg["required_doctor_channels"]:
            info = doctor_channels.get(ch)
            if not info or info.get("status") != "ok":
                warnings.append(f"doctor 渠道 {ch} 未就绪")

    if snapshot.get("structured_review_complete") is False:
        structured_review_complete = False
        warnings.append("未完成结构化复核（仅 Web 候选，未校验关键字段）")

    passed = len(issues) == 0

    return AuditResult(
        passed=passed,
        issues=issues,
        warnings=warnings,
        structured_review_complete=structured_review_complete,
    )


def _parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
