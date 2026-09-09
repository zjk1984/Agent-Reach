# -*- coding: utf-8
"""Sector gap-down fade buffer — temporary macro_veto bump on high-open/low-close patterns."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_SECTOR_GAP_NEUTRAL: dict[str, Any] = {
    "enabled": True,
    "sectors": ("半导体", "存储", "AI算力"),
    "min_open_gap_pct": 0.8,
    "min_fade_pct": 2.0,
    "macro_veto_bump": 3.0,
    "max_macro_veto": 45.0,
}


def sector_gap_guard_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    intraday = dict((settings or {}).get("intraday") or {})
    block = dict(intraday.get("sector_gap_guard") or {})
    out = {**_SECTOR_GAP_NEUTRAL, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", True))
    sectors = out.get("sectors")
    if isinstance(sectors, str):
        out["sectors"] = tuple(s.strip() for s in sectors.split(",") if s.strip())
    elif isinstance(sectors, list):
        out["sectors"] = tuple(str(s).strip() for s in sectors if str(s).strip())
    return out


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_open_gap_pct(row: dict[str, Any]) -> Optional[float]:
    prev = _optional_float(row.get("prev_close") or row.get("pre_close"))
    open_px = _optional_float(row.get("open"))
    if prev is None or prev <= 0 or open_px is None or open_px <= 0:
        return None
    return (open_px - prev) / prev * 100.0


def _sector_matches(label: str, sectors: tuple[str, ...]) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    return any(token in text for token in sectors)


def detect_sector_gap_down_fade(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Detect held-sector high-open / low-close fade for intraday macro buffer."""
    cfg = sector_gap_guard_cfg(settings)
    if not cfg.get("enabled", True):
        return None

    sectors = tuple(cfg.get("sectors") or ())
    if not sectors:
        return None

    min_open = float(cfg.get("min_open_gap_pct", 0.8))
    min_fade = float(cfg.get("min_fade_pct", 2.0))

    pf = snapshot.get("portfolio") or {}
    best: Optional[dict[str, Any]] = None

    for holding in pf.get("holdings") or []:
        if int(holding.get("shares") or 0) <= 0:
            continue
        sector = str(holding.get("sector") or holding.get("industry") or "")
        if not _sector_matches(sector, sectors):
            continue

        code = _normalize_code(str(holding.get("code") or ""))
        row = dict(holding)
        for sym in snapshot.get("symbols") or []:
            if _normalize_code(str(sym.get("code") or "")) == code:
                row = {**sym, **row}
                break

        open_gap = _row_open_gap_pct(row)
        change_pct = _optional_float(row.get("change_pct"))
        if open_gap is None or change_pct is None:
            continue
        if open_gap < min_open:
            continue
        fade = open_gap - change_pct
        if fade < min_fade:
            continue

        candidate = {
            "code": code,
            "name": str(holding.get("name") or code),
            "sector": sector,
            "open_gap_pct": round(open_gap, 2),
            "change_pct": round(change_pct, 2),
            "fade_pct": round(fade, 2),
        }
        if best is None or float(candidate["fade_pct"]) > float(best["fade_pct"]):
            best = candidate

    return best


def intraday_macro_veto_with_sector_buffer(
    base_macro_veto: float,
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[float, Optional[str]]:
    """Return effective macro_veto and optional overlay note for sector gap-down fade."""
    fade = detect_sector_gap_down_fade(snapshot, settings=settings)
    if not fade:
        return float(base_macro_veto), None

    cfg = sector_gap_guard_cfg(settings)
    bump = float(cfg.get("macro_veto_bump", 3.0))
    cap = float(cfg.get("max_macro_veto", 45.0))
    effective = min(cap, float(base_macro_veto) + bump)
    note = (
        f"（{fade.get('name')} {fade.get('sector')} 高开低走 "
        f"fade {float(fade.get('fade_pct') or 0):.1f}%，macro_veto +{bump:.0f}→{effective:.0f}）"
    )
    return effective, note
