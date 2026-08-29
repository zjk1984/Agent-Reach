# -*- coding: utf-8
"""Decimal financial verification (adapted from ai-berkshire financial_rigor)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN
from typing import Any, Optional

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)


def exact(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


@dataclass
class MarketCapCheck:
    ok: bool
    calculated: float
    reported: float
    deviation_pct: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "calculated": self.calculated,
            "reported": self.reported,
            "deviation_pct": self.deviation_pct,
            "message": self.message,
        }


def verify_market_cap(
    price: Any,
    shares: Any,
    reported_cap: Any,
    *,
    warn_pct: float = 1.0,
    fail_pct: float = 5.0,
) -> MarketCapCheck:
    p = exact(price)
    s = exact(shares)
    r = exact(reported_cap)
    calculated = _CTX.multiply(p, s)
    if r == 0:
        return MarketCapCheck(
            ok=False,
            calculated=float(calculated),
            reported=float(r),
            deviation_pct=100.0,
            message="报告市值为 0，无法验算",
        )
    deviation = abs(float(calculated - r) / float(r)) * 100
    if deviation > fail_pct:
        msg = f"市值偏差 {deviation:.2f}% > {fail_pct:g}%（单位/股本/股价可能不一致）"
        return MarketCapCheck(False, float(calculated), float(r), deviation, msg)
    if deviation > warn_pct:
        msg = f"市值偏差 {deviation:.2f}% 在警戒区间（≤{fail_pct:g}%）"
        return MarketCapCheck(True, float(calculated), float(r), deviation, msg)
    return MarketCapCheck(
        True,
        float(calculated),
        float(r),
        deviation,
        f"市值验算通过，偏差 {deviation:.2f}%",
    )


def verify_valuation_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Best-effort PE/PB from snapshot price + optional fundamentals."""
    price = snapshot.get("price")
    if price is None:
        return {"skipped": True, "reason": "missing price"}
    p = exact(price)
    out: dict[str, Any] = {"price": float(p)}
    eps = snapshot.get("eps_ttm") or snapshot.get("eps")
    bvps = snapshot.get("bvps") or snapshot.get("book_value_per_share")
    if eps is not None:
        e = exact(eps)
        if e != 0:
            out["pe_ttm"] = float(_CTX.divide(p, e))
    if bvps is not None:
        b = exact(bvps)
        if b != 0:
            out["pb"] = float(_CTX.divide(p, b))
    return out


def verify_snapshot_financials(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Run market-cap and valuation checks when snapshot carries enough fields."""
    checks: dict[str, Any] = {"valuation": verify_valuation_from_snapshot(snapshot)}
    price = snapshot.get("price")
    shares = snapshot.get("total_shares") or snapshot.get("shares_outstanding")
    reported = snapshot.get("market_cap") or snapshot.get("total_market_cap")
    if price is not None and shares is not None and reported is not None:
        mc = verify_market_cap(price, shares, reported)
        checks["market_cap"] = mc.to_dict()
        checks["ok"] = mc.ok
    else:
        checks["market_cap"] = {"skipped": True, "reason": "missing price/shares/market_cap"}
        checks["ok"] = True
    return checks


def append_verify_deviations(verify_dict: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Return deviation strings to merge into verify result."""
    fin = verify_snapshot_financials(snapshot)
    mc = fin.get("market_cap") or {}
    if mc.get("skipped"):
        return []
    if mc.get("ok") is False:
        return [f"财务验算：{mc.get('message', '市值偏差超标')}"]
    dev = mc.get("deviation_pct")
    if dev is not None and float(dev) > 1.0:
        return [f"财务验算：{mc.get('message')}"]
    return []
