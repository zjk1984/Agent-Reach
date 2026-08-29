# -*- coding: utf-8
"""Quality screen — 7-rule pass/fail from snapshot fundamentals (watchlist gate)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QualityScreenResult:
    code: str
    name: str
    passed: bool
    failed_rules: list[str] = field(default_factory=list)
    waived_rules: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "passed": self.passed,
            "failed_rules": list(self.failed_rules),
            "waived_rules": list(self.waived_rules),
            "metrics": dict(self.metrics),
            "reason": self.reason,
        }


def _f(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def screen_from_snapshot(
    snapshot: dict[str, Any],
    *,
    enriched: dict[str, Any] | None = None,
) -> QualityScreenResult:
    """Lightweight screen using fields already on daily-run snapshots."""
    row = {**(enriched or {}), **snapshot}
    code = str(row.get("code") or "")
    name = str(row.get("name") or code)
    metrics: dict[str, Any] = {}
    failed: list[str] = []
    waived: list[str] = []

    roe = _f(row.get("roe") or row.get("roe_ttm"))
    metrics["roe"] = roe
    if roe is not None and roe < 8:
        gm = _f(row.get("gross_margin") or row.get("gross_margin_pct"))
        ocf_pos = _f(row.get("operating_cashflow")) or 0
        if gm and gm > 30 and ocf_pos > 0:
            waived.append("①ROE<8 战略投入期豁免")
        else:
            failed.append("①10年ROE<8%")

    fcf_5y = _f(row.get("fcf_5y_cumulative") or row.get("free_cashflow_5y"))
    metrics["fcf_5y"] = fcf_5y
    if fcf_5y is not None and fcf_5y < 0:
        failed.append("②5年累计FCF为负")

    interest_cov = _f(row.get("interest_coverage") or row.get("ebit_to_interest"))
    metrics["interest_coverage"] = interest_cov
    sector = str(row.get("sector") or row.get("industry") or "")
    if interest_cov is not None and interest_cov < 2 and "银行" not in sector and "保险" not in sector:
        failed.append("③利息覆盖<2x")

    gm = _f(row.get("gross_margin") or row.get("gross_margin_pct"))
    metrics["gross_margin"] = gm
    roe_val = roe or 0
    if gm is not None and gm < 15:
        if roe_val > 20 and (_f(row.get("ocf_to_net_income")) or 0) > 1:
            waived.append("④⑥高周转薄利豁免")
        else:
            failed.append("④长期毛利率<15%")

    ocf_ni = _f(row.get("ocf_to_net_income") or row.get("operating_cashflow_ratio"))
    metrics["ocf_to_net_income"] = ocf_ni
    if ocf_ni is not None and ocf_ni < 0.7:
        failed.append("⑤经营现金流/净利润<0.7")

    nm = _f(row.get("net_margin") or row.get("net_margin_pct"))
    metrics["net_margin"] = nm
    if nm is not None and nm < 5:
        if gm and gm > 30:
            waived.append("⑥净利率<5% 主动低利润豁免")
        elif not any("高周转" in w for w in waived):
            failed.append("⑥长期净利率<5%")

    dilution = _f(row.get("share_dilution_5y_pct"))
    metrics["share_dilution_5y_pct"] = dilution
    if dilution is not None and dilution > 20:
        failed.append("⑦5年股本膨胀>20%")

    if not failed and all(v is None for v in metrics.values()):
        return QualityScreenResult(
            code,
            name,
            passed=True,
            metrics=metrics,
            reason="数据不足，quality-screen 放行（待深研补全）",
        )

    passed = len(failed) == 0
    reason = "通过" if passed else f"未通过：{'; '.join(failed)}"
    if waived:
        reason += f"（豁免：{'; '.join(waived)}）"
    return QualityScreenResult(code, name, passed, failed, waived, metrics, reason)


def passes_watchlist_gate(
    snapshot: dict[str, Any],
    *,
    enriched: dict[str, Any] | None = None,
    settings: dict | None = None,
) -> tuple[bool, str]:
    from agent_reach.daily_run.berkshire.config import berkshire_enabled

    if not berkshire_enabled(settings, key="quality_screen_watchlist"):
        return True, "quality_screen disabled"
    result = screen_from_snapshot(snapshot, enriched=enriched)
    if result.passed:
        return True, result.reason
    if "数据不足" in result.reason:
        return True, result.reason
    return False, result.reason
