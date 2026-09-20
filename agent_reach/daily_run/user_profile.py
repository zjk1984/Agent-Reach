# -*- coding: utf-8
"""User investment profile for watchlist scoring (OpenStock onboarding pattern)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code


def user_profile_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "user_profile.json"


def default_user_profile() -> dict[str, Any]:
    return {
        "risk_tolerance": "moderate",
        "investment_goals": "",
        "preferred_sectors": [],
        "preferred_industry": "",
        "country": "CN",
    }


def load_user_profile() -> dict[str, Any]:
    path = user_profile_path()
    if not path.exists():
        return default_user_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_user_profile()
    if not isinstance(data, dict):
        return default_user_profile()
    merged = default_user_profile()
    merged.update({k: v for k, v in data.items() if v is not None})
    sectors = merged.get("preferred_sectors")
    if isinstance(sectors, str):
        merged["preferred_sectors"] = [s.strip() for s in sectors.split(",") if s.strip()]
    elif not isinstance(sectors, list):
        merged["preferred_sectors"] = []
    return merged


def save_user_profile(profile: dict[str, Any]) -> Path:
    path = user_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def user_profile_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("user_profile") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "sector_match_boost": float(raw.get("sector_match_boost") or 3.0),
        "sector_mismatch_penalty": float(raw.get("sector_mismatch_penalty") or 2.0),
        "filter_non_preferred": raw.get("filter_non_preferred", False) is True,
    }


def candidate_sector(row: dict[str, Any], settings: Optional[dict[str, Any]] = None) -> str:
    sector = str(row.get("sector") or "").strip()
    if sector:
        return sector
    from agent_reach.daily_run.watchlist_manager import _sector_for_candidate

    return _sector_for_candidate(row, settings or {})


def profile_sector_match(sector: str, profile: dict[str, Any]) -> bool:
    preferred = [str(s).strip() for s in (profile.get("preferred_sectors") or []) if str(s).strip()]
    if not preferred:
        return True
    sector = str(sector or "").strip()
    if not sector:
        return False
    return any(p in sector or sector in p for p in preferred)


def watchlist_profile_score_adjustment(
    candidate: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    profile: Optional[dict[str, Any]] = None,
) -> float:
    cfg = user_profile_cfg(settings)
    if not cfg["enabled"]:
        return 0.0
    prof = profile or load_user_profile()
    sector = candidate_sector(candidate, settings)
    if profile_sector_match(sector, prof):
        return cfg["sector_match_boost"]
    if prof.get("preferred_sectors"):
        return -cfg["sector_mismatch_penalty"]
    return 0.0


def watchlist_blocked_by_profile(
    candidate: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    profile: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    cfg = user_profile_cfg(settings)
    if not cfg["enabled"] or not cfg["filter_non_preferred"]:
        return None
    prof = profile or load_user_profile()
    preferred = prof.get("preferred_sectors") or []
    if not preferred:
        return None
    sector = candidate_sector(candidate, settings)
    if profile_sector_match(sector, prof):
        return None
    return f"不在偏好板块（{', '.join(preferred[:3])}）"
