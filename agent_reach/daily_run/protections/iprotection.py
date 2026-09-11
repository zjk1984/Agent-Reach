# -*- coding: utf-8
"""ProtectionReturn contract (Freqtrade IProtection-inspired)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class ProtectionReturn:
    lock: bool
    until: Optional[datetime]
    reason: str
    lock_side: str = "*"
    scope: str = "pair"
    code: str = ""
    name: str = ""
    protection: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock": self.lock,
            "until": self.until.isoformat() if self.until else None,
            "reason": self.reason,
            "lock_side": self.lock_side,
            "scope": self.scope,
            "code": self.code,
            "name": self.name,
            "protection": self.protection,
        }


def protections_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    root = dict((settings or {}).get("protections") or {})
    root["enabled"] = root.get("enabled", True) is not False
    return root


def protections_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return protections_cfg(settings).get("enabled", True) is not False
