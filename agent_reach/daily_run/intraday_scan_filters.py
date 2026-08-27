# -*- coding: utf-8
"""Filter lunch/midday anchor scans from MSS trend and lookback weighting."""

from __future__ import annotations

from typing import Any, Optional

_MACRO_BREAKDOWN_KEYS: tuple[str, ...] = ("fx", "flow", "global", "sentiment")
_PRICE_BREAKDOWN_KEYS: tuple[str, ...] = ("technical", "quant", "risk")


def is_midday_anchor_scan(scan: dict[str, Any]) -> bool:
    return str(scan.get("source") or "") == "midday" or bool(scan.get("trend_excluded"))


def scans_for_trend_detection(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop lunch anchor scans so stale 11:30 prices do not fake inflections."""
    if not scans:
        return []
    filtered = [s for s in scans if not is_midday_anchor_scan(s)]
    if len(filtered) >= 2:
        return filtered
    if len(scans) >= 2:
        return list(scans[:-1])
    return list(scans)


def last_session_scan(scans: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Most recent scan that is not a midday lunch anchor."""
    for scan in reversed(scans):
        if not is_midday_anchor_scan(scan):
            return scan
    return scans[-1] if scans else None


def merge_midday_breakdown(
    base: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    """Refresh macro factors only; keep price-sensitive MSS legs from last session."""
    out = dict(base or {})
    for key, val in (live or {}).items():
        if key.startswith("_") or key.endswith("_ref"):
            out[key] = val
        elif key in _MACRO_BREAKDOWN_KEYS:
            out[key] = val
    for key in _PRICE_BREAKDOWN_KEYS:
        if key not in out and key in (live or {}):
            out[key] = live[key]
    return out


def preserve_session_price_fields(
    snapshot: dict[str, Any],
    session_scan: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Carry forward last continuous-session price/technicals during lunch."""
    if not session_scan:
        return snapshot
    out = dict(snapshot)
    for key in ("price", "change_pct", "ma20", "position_20d", "volume_ratio", "vwap_deviation_pct"):
        if out.get(key) is None and session_scan.get(key) is not None:
            out[key] = session_scan[key]
    base_bd = dict(out.get("mss_breakdown") or {})
    scan_bd = dict(session_scan.get("mss_breakdown") or {})
    for key in _PRICE_BREAKDOWN_KEYS:
        if key in scan_bd:
            base_bd[key] = scan_bd[key]
    if base_bd:
        out["mss_breakdown"] = base_bd
    if out.get("mss_final") is None and session_scan.get("mss_final") is not None:
        out["mss_final"] = session_scan["mss_final"]
    return out
