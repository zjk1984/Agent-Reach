# -*- coding: utf-8
"""Price target alerts (OpenStock-inspired): ABOVE/BELOW with Feishu push."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

AlertCondition = Literal["ABOVE", "BELOW"]

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("agent_reach.daily_run")


def price_alerts_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("price_alerts") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "default_expiry_days": max(1, int(raw.get("default_expiry_days") or 90)),
        "push_feishu": raw.get("push_feishu", True) is not False,
        "feishu_template": str(raw.get("feishu_template") or "orange"),
        "include_watchlist_codes": raw.get("include_watchlist_codes", True) is not False,
        "include_holding_codes": raw.get("include_holding_codes", True) is not False,
    }


def alerts_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "price_alerts.json"


@dataclass
class PriceAlert:
    id: str
    code: str
    name: str
    target_price: float
    condition: AlertCondition
    active: bool = True
    triggered: bool = False
    expires_at: str = ""
    created_at: str = ""
    source: str = "manual"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "target_price": float(self.target_price),
            "condition": self.condition,
            "active": self.active,
            "triggered": self.triggered,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PriceAlert:
        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex[:12]),
            code=_normalize_code(str(raw.get("code") or "")),
            name=str(raw.get("name") or raw.get("code") or ""),
            target_price=float(raw.get("target_price") or 0),
            condition=str(raw.get("condition") or "ABOVE").upper(),  # type: ignore[arg-type]
            active=bool(raw.get("active", True)),
            triggered=bool(raw.get("triggered", False)),
            expires_at=str(raw.get("expires_at") or ""),
            created_at=str(raw.get("created_at") or ""),
            source=str(raw.get("source") or "manual"),
            note=str(raw.get("note") or ""),
        )


def load_alerts() -> list[PriceAlert]:
    path = alerts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = data.get("alerts") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[PriceAlert] = []
    for row in rows:
        if isinstance(row, dict) and row.get("code"):
            out.append(PriceAlert.from_dict(row))
    return out


def save_alerts(alerts: list[PriceAlert]) -> Path:
    path = alerts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "alerts": [a.to_dict() for a in alerts],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def add_alert(
    *,
    code: str,
    target_price: float,
    condition: AlertCondition,
    name: str = "",
    note: str = "",
    expiry_days: Optional[int] = None,
    settings: Optional[dict[str, Any]] = None,
) -> PriceAlert:
    cfg = price_alerts_cfg(settings)
    code = _normalize_code(code)
    if not code:
        raise ValueError("code required")
    if target_price <= 0:
        raise ValueError("target_price must be positive")
    cond = str(condition).upper()
    if cond not in ("ABOVE", "BELOW"):
        raise ValueError("condition must be ABOVE or BELOW")
    days = expiry_days if expiry_days is not None else cfg["default_expiry_days"]
    now = datetime.now(timezone.utc)
    alert = PriceAlert(
        id=uuid.uuid4().hex[:12],
        code=code,
        name=name or code,
        target_price=float(target_price),
        condition=cond,  # type: ignore[arg-type]
        active=True,
        triggered=False,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=days)).isoformat(),
        source="manual",
        note=note,
    )
    alerts = load_alerts()
    alerts.append(alert)
    save_alerts(alerts)
    return alert


def remove_alert(alert_id: str) -> bool:
    alerts = load_alerts()
    before = len(alerts)
    alerts = [a for a in alerts if a.id != alert_id]
    if len(alerts) == before:
        return False
    save_alerts(alerts)
    return True


def _is_expired(alert: PriceAlert, *, now: Optional[datetime] = None) -> bool:
    if not alert.expires_at:
        return False
    try:
        exp = datetime.fromisoformat(alert.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    ref = now or datetime.now(timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return ref >= exp


def active_alerts(settings: Optional[dict[str, Any]] = None) -> list[PriceAlert]:
    if not price_alerts_cfg(settings)["enabled"]:
        return []
    now = datetime.now(timezone.utc)
    return [
        a
        for a in load_alerts()
        if a.active and not a.triggered and not _is_expired(a, now=now)
    ]


def _fetch_prices(codes: list[str], settings: Optional[dict[str, Any]] = None) -> dict[str, float]:
    if not codes:
        return {}
    from agent_reach.daily_run.snapshot_builder import fetch_quotes_map
    from agent_reach.config import Config

    try:
        quotes = fetch_quotes_map(codes, Config(), settings=settings)
    except Exception as exc:
        logger.warning("price_alerts quote fetch failed: {}", exc)
        return {}
    out: dict[str, float] = {}
    for code in codes:
        norm = _normalize_code(code)
        row = quotes.get(norm) or quotes.get(code) or {}
        price = row.get("price") if isinstance(row, dict) else None
        if price is not None:
            try:
                out[norm] = float(price)
            except (TypeError, ValueError):
                continue
    return out


def _condition_met(condition: AlertCondition, current: float, target: float) -> bool:
    if condition == "ABOVE":
        return current >= target
    return current <= target


def check_price_alerts(
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    config=None,
) -> dict[str, Any]:
    """Evaluate active alerts; mark triggered and optionally push Feishu."""
    cfg = price_alerts_cfg(settings)
    if not cfg["enabled"]:
        return {"skipped": True, "reason": "price_alerts disabled"}

    alerts = active_alerts(settings)
    if not alerts:
        return {"checked": 0, "triggered": [], "message": "no active alerts"}

    codes = sorted({_normalize_code(a.code) for a in alerts})
    prices = _fetch_prices(codes, settings=settings)
    triggered_rows: list[dict[str, Any]] = []
    all_alerts = load_alerts()
    by_id = {a.id: a for a in all_alerts}

    for alert in alerts:
        price = prices.get(_normalize_code(alert.code))
        if price is None:
            continue
        if not _condition_met(alert.condition, price, alert.target_price):
            continue
        stored = by_id.get(alert.id)
        if stored is None:
            continue
        stored.triggered = True
        stored.active = False
        row = {
            **stored.to_dict(),
            "current_price": price,
            "message": (
                f"{stored.name} ({stored.code}) 现价 ¥{price:.2f} "
                f"{'≥' if stored.condition == 'ABOVE' else '≤'} 目标 ¥{stored.target_price:.2f}"
            ),
        }
        triggered_rows.append(row)

    if triggered_rows:
        save_alerts(list(by_id.values()))

    feishu_result = None
    if push and cfg["push_feishu"] and triggered_rows:
        feishu_result = _push_triggered_alerts(triggered_rows, settings=settings, config=config)

    return {
        "checked": len(alerts),
        "triggered": triggered_rows,
        "feishu": feishu_result,
        "prices_found": len(prices),
    }


def _push_triggered_alerts(
    triggered: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> Optional[dict[str, Any]]:
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import FeishuError, send_card

    cfg_obj = config or Config()
    tpl = price_alerts_cfg(settings)["feishu_template"]
    lines = ["## 🔔 价位告警触发", ""]
    for row in triggered[:8]:
        lines.append(f"- {row.get('message')}")
        note = str(row.get("note") or "").strip()
        if note:
            lines.append(f"  - 备注：{note[:80]}")
    body = "\n".join(lines)
    try:
        return send_card(cfg_obj, "价位告警", body, template=tpl)
    except FeishuError as exc:
        logger.warning("price_alerts Feishu push failed: {}", exc)
        return {"error": str(exc)}


def render_alerts_markdown(settings: Optional[dict[str, Any]] = None) -> str:
    rows = active_alerts(settings)
    if not rows:
        return ""
    lines = ["**🔔 活跃价位告警**", ""]
    for a in rows[:10]:
        op = "≥" if a.condition == "ABOVE" else "≤"
        lines.append(f"- **{a.name}** ({a.code}) 目标 {op} ¥{a.target_price:.2f}")
    return "\n".join(lines)
