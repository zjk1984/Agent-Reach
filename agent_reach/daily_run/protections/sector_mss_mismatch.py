# -*- coding: utf-8
"""High MSS + sector underperformance → cap verdict / block buy."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.protections.iprotection import ProtectionReturn, protections_cfg
from agent_reach.daily_run.snapshot_builder import _normalize_code


def _sector_mss_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = protections_cfg(settings)
    block = dict(root.get("sector_mss_mismatch") or {})
    sectors = block.get("sectors") or ["半导体", "存储", "AI算力", "消费电子"]
    if isinstance(sectors, str):
        sectors = [s.strip() for s in sectors.split(",") if s.strip()]
    return {
        "enabled": block.get("enabled", True) is not False,
        "min_mss": float(block.get("min_mss", 49.0)),
        "min_underperform_index_pct": float(block.get("min_underperform_index_pct", 1.5)),
        "sectors": tuple(str(s).strip() for s in sectors if str(s).strip()),
        "block_buy": block.get("block_buy", True) is not False,
        "verdict_cap": str(block.get("verdict_cap") or "观察"),
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sector_matches(label: str, sectors: tuple[str, ...]) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    return any(token in text for token in sectors)


def _symbol_row(snapshot: dict[str, Any], code: str) -> dict[str, Any]:
    norm = _normalize_code(code)
    for sym in snapshot.get("symbols") or []:
        if isinstance(sym, dict) and _normalize_code(str(sym.get("code") or "")) == norm:
            return sym
    pf = snapshot.get("portfolio") or {}
    for holding in pf.get("holdings") or []:
        if isinstance(holding, dict) and _normalize_code(str(holding.get("code") or "")) == norm:
            return holding
    return {}


def _index_change_pct(snapshot: dict[str, Any]) -> Optional[float]:
    macro = snapshot.get("macro_ctx") or snapshot.get("macro") or {}
    indices = macro.get("indices") or {}
    for key in ("sh000300", "000300", "hs300"):
        row = indices.get(key) if isinstance(indices, dict) else None
        if isinstance(row, dict):
            chg = _optional_float(row.get("change_pct"))
            if chg is not None:
                return chg
    for sym in snapshot.get("symbols") or []:
        if not isinstance(sym, dict):
            continue
        if str(sym.get("code") or "") in {"000300", "399300"}:
            chg = _optional_float(sym.get("change_pct"))
            if chg is not None:
                return chg
    return _optional_float(snapshot.get("index_change_pct"))


def detect_sector_mss_mismatch(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    cfg = _sector_mss_cfg(settings)
    if not cfg["enabled"]:
        return None

    code = str(report.get("code") or "")
    mss = _optional_float(report.get("mss_final"))
    if mss is None or mss < float(cfg["min_mss"]):
        return None

    row = _symbol_row(snapshot, code)
    sector = str(row.get("sector") or row.get("industry") or report.get("sector") or "")
    if not _sector_matches(sector, cfg["sectors"]):
        return None

    sym_chg = _optional_float(row.get("change_pct") or snapshot.get("change_pct"))
    idx_chg = _index_change_pct(snapshot)
    if sym_chg is None or idx_chg is None:
        return None

    gap = float(idx_chg) - float(sym_chg)
    if gap < float(cfg["min_underperform_index_pct"]):
        return None

    return {
        "code": _normalize_code(code),
        "name": str(report.get("name") or row.get("name") or code),
        "sector": sector,
        "mss_final": round(mss, 2),
        "change_pct": round(sym_chg, 2),
        "index_change_pct": round(idx_chg, 2),
        "underperform_pct": round(gap, 2),
    }


def evaluate_sector_mss_mismatch(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    side: str,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[ProtectionReturn]:
    cfg = _sector_mss_cfg(settings)
    if not cfg["enabled"]:
        return None

    hit = detect_sector_mss_mismatch(snapshot=snapshot, report=report, settings=settings)
    if hit is None:
        return None

    side_l = str(side or "").lower()
    if side_l == "buy" and cfg["block_buy"]:
        reason = (
            f"sector_mss_mismatch：MSS {hit['mss_final']:.1f} 但 {hit['sector']} "
            f"跌 {hit['change_pct']:+.2f}%（弱于指数 {hit['underperform_pct']:.1f}%），禁止接飞刀买入"
        )
        return ProtectionReturn(
            lock=True,
            until=None,
            reason=reason,
            lock_side="buy",
            scope="pair",
            code=hit["code"],
            name=hit["name"],
            protection="sector_mss_mismatch",
        )
    return None


def protection_verdict_cap(
    *,
    snapshot: dict[str, Any],
    report: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    cfg = _sector_mss_cfg(settings)
    if not cfg["enabled"]:
        return None
    if detect_sector_mss_mismatch(snapshot=snapshot, report=report, settings=settings) is None:
        return None
    return str(cfg["verdict_cap"])
