# -*- coding: utf-8
"""Watchlist adjustments — allowed only at morning and close."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

WatchlistPhase = Literal["morning", "close"]

ALLOWED_WATCHLIST_PHASES = frozenset({"morning", "close"})


@dataclass
class WatchlistChange:
    action: str  # add | remove
    code: str
    name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "code": self.code,
            "name": self.name,
            "reason": self.reason,
        }


@dataclass
class WatchlistAdjustResult:
    applied: bool
    portfolio: dict[str, Any]
    changes: list[WatchlistChange] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "message": self.message,
            "changes": [c.to_dict() for c in self.changes],
        }


def watchlist_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return settings.get("watchlist") or {}


def is_watchlist_adjust_enabled(settings: dict[str, Any]) -> bool:
    return bool(watchlist_settings(settings).get("auto_adjust_enabled", True))


def can_adjust_watchlist(phase: str) -> bool:
    return phase in ALLOWED_WATCHLIST_PHASES


def max_watchlist_size(settings: dict[str, Any]) -> int:
    return int(watchlist_settings(settings).get("max_size", 20))


def adjust_watchlist(
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    phase: WatchlistPhase,
    *,
    verify: Optional[dict[str, Any]] = None,
    sold_codes: Optional[list[dict[str, Any]]] = None,
) -> WatchlistAdjustResult:
    """Update watchlist membership — only valid for morning or close."""
    if not can_adjust_watchlist(phase):
        return WatchlistAdjustResult(
            applied=False,
            portfolio=portfolio,
            message=f"观察池仅可在早盘/复盘调整，当前 phase={phase}",
        )
    if not is_watchlist_adjust_enabled(settings):
        return WatchlistAdjustResult(applied=False, portfolio=portfolio, message="watchlist.auto_adjust 未启用")

    pf = _copy_portfolio(portfolio)
    enriched = _enriched_symbols(snapshot)
    changes: list[WatchlistChange] = []
    thresholds = settings.get("thresholds", {})
    macro_veto = float(thresholds.get("macro_veto", 40))
    held_codes = {_normalize_code(str(h.get("code", ""))) for h in pf.get("holdings") or []}

    if phase == "close" and sold_codes:
        for item in sold_codes:
            code = _normalize_code(str(item.get("code", "")))
            if not code or code in held_codes:
                continue
            if _has_code(pf.get("watchlist") or [], code):
                continue
            name = str(item.get("name") or code)
            pf.setdefault("watchlist", []).append({"code": code, "name": name})
            changes.append(WatchlistChange("add", code, name, "盘中卖出，收盘复盘回收入观察池"))

    # Remove: already held, missing quote, or weak momentum
    kept: list[dict[str, Any]] = []
    for w in pf.get("watchlist") or []:
        code = _normalize_code(str(w.get("code", "")))
        row = {**w, **enriched.get(code, {})}
        if code in held_codes:
            changes.append(
                WatchlistChange("remove", code, str(w.get("name", code)), "已持仓，移出观察池")
            )
            continue
        chg = row.get("change_pct")
        score = _symbol_score(row, snapshot, settings)
        if chg is not None and float(chg) <= -8:
            changes.append(
                WatchlistChange("remove", code, str(w.get("name", code)), f"跌幅 {float(chg):.1f}% 过大")
            )
            continue
        if score < macro_veto:
            changes.append(
                WatchlistChange("remove", code, str(w.get("name", code)), f"评分 {score:.0f} 低于否决线")
            )
            continue
        kept.append(dict(w))

    pf["watchlist"] = kept

    # Morning: optionally add candidates from config
    if phase == "morning":
        for cand in watchlist_settings(settings).get("candidates") or []:
            code = _normalize_code(str(cand.get("code", "")))
            if not code or code in held_codes or _has_code(pf["watchlist"], code):
                continue
            if len(pf["watchlist"]) >= max_watchlist_size(settings):
                break
            name = str(cand.get("name") or code)
            pf["watchlist"].append({"code": code, "name": name})
            changes.append(WatchlistChange("add", code, name, "早盘候选纳入观察池"))

    # Close: trim to max size by score
    pf["watchlist"] = _trim_by_score(
        pf["watchlist"],
        enriched,
        snapshot,
        settings,
        max_watchlist_size(settings),
        changes,
    )

    if verify and verify.get("verdict_current") == "回避":
        # Macro risk-off: keep only top 3 watchlist names
        pf["watchlist"] = _trim_by_score(
            pf["watchlist"],
            enriched,
            snapshot,
            settings,
            min(3, max_watchlist_size(settings)),
            changes,
            reason_prefix="宏观回避，收缩观察池",
        )

    if not changes:
        return WatchlistAdjustResult(applied=False, portfolio=pf, message="观察池无变更")

    return WatchlistAdjustResult(
        applied=True,
        portfolio=pf,
        changes=changes,
        message=f"观察池调整 {len(changes)} 项（{phase}）",
    )


def render_watchlist_adjust_markdown(result: WatchlistAdjustResult) -> str:
    if not result.applied:
        return f"**观察池：** 未调整 — {result.message}"
    lines = [f"**观察池调整（{result.message}）：**"]
    for c in result.changes:
        verb = "纳入" if c.action == "add" else "移出"
        lines.append(f"- {verb} **{c.name}** ({c.code}) — {c.reason}")
    return "\n".join(lines)


def _trim_by_score(
    watchlist: list[dict[str, Any]],
    enriched: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
    settings: dict[str, Any],
    limit: int,
    changes: list[WatchlistChange],
    *,
    reason_prefix: str = "超出上限，按评分保留",
) -> list[dict[str, Any]]:
    if len(watchlist) <= limit:
        return watchlist
    ranked = sorted(
        watchlist,
        key=lambda w: _symbol_score({**w, **enriched.get(_normalize_code(str(w.get("code", ""))), {})}, snapshot, settings),
        reverse=True,
    )
    kept = ranked[:limit]
    kept_codes = {_normalize_code(str(w.get("code", ""))) for w in kept}
    for w in watchlist:
        code = _normalize_code(str(w.get("code", "")))
        if code not in kept_codes:
            changes.append(
                WatchlistChange("remove", code, str(w.get("name", code)), reason_prefix)
            )
    return kept


def _symbol_score(row: dict[str, Any], snapshot: dict[str, Any], settings: dict[str, Any]) -> float:
    base = float(snapshot.get("mss_final") or 50)
    breakdown = snapshot.get("mss_breakdown") or {}
    if breakdown:
        from agent_reach.daily_run.verdict import compute_mss

        base = float(compute_mss(breakdown, settings))
    chg = row.get("change_pct")
    if chg is not None:
        base += float(chg) * 0.5
    return base


def _enriched_symbols(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for w in snapshot.get("watchlist") or []:
        code = _normalize_code(str(w.get("code", "")))
        out[code] = dict(w)
    for h in (snapshot.get("portfolio") or {}).get("holdings") or []:
        code = _normalize_code(str(h.get("code", "")))
        out[code] = {**out.get(code, {}), **dict(h)}
    return out


def _has_code(watchlist: list[dict[str, Any]], code: str) -> bool:
    return any(_normalize_code(str(w.get("code", ""))) == code for w in watchlist)


def _copy_portfolio(portfolio: dict[str, Any]) -> dict[str, Any]:
    pf = dict(portfolio)
    pf["holdings"] = [dict(h) for h in (portfolio.get("holdings") or [])]
    pf["watchlist"] = [dict(w) for w in (portfolio.get("watchlist") or [])]
    return pf


def collect_intraday_sold_codes(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Read today's sell actions from trade ledger for close watchlist recycle."""
    from agent_reach.daily_run.portfolio_manager import default_ledger_path
    from datetime import date
    import json

    path = default_ledger_path()
    if not path.exists():
        return []
    today = date.today().isoformat()
    sold: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not str(entry.get("at", "")).startswith(today):
            continue
        for action in entry.get("actions") or []:
            if action.get("side") == "sell":
                sold.append({"code": action.get("code"), "name": action.get("name")})
    return sold
