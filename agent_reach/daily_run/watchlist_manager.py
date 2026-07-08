# -*- coding: utf-8
"""Watchlist adjustments — allowed only at morning and close."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from agent_reach.daily_run.portfolio_manager import (
    max_total_symbols,
    unique_symbol_count,
    watchlist_capacity,
)
from agent_reach.daily_run.symbols import build_enriched_symbols, copy_portfolio
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


def max_watchlist_size(settings: dict[str, Any], portfolio: Optional[dict[str, Any]] = None) -> int:
    """Legacy helper — when portfolio given, returns capacity under total cap."""
    if portfolio is not None:
        return watchlist_capacity(settings, portfolio)
    wl = watchlist_settings(settings)
    if "max_size" in wl:
        return int(wl["max_size"])
    return max_total_symbols(settings)


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

    pf = copy_portfolio(portfolio)
    enriched = build_enriched_symbols(snapshot)
    changes: list[WatchlistChange] = []
    thresholds = settings.get("thresholds", {})
    macro_veto = float(thresholds.get("macro_veto", 40))
    held_codes = {_normalize_code(str(h.get("code", ""))) for h in pf.get("holdings") or []}
    base_mss = _snapshot_base_mss(snapshot, settings)

    if phase == "close" and sold_codes:
        for item in sold_codes:
            code = _normalize_code(str(item.get("code", "")))
            if not code or code in held_codes:
                continue
            if _has_code(pf.get("watchlist") or [], code):
                continue
            if unique_symbol_count(pf) >= max_total_symbols(settings):
                break
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
        score = _symbol_score(row, base_mss=base_mss)
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
            if unique_symbol_count(pf) >= max_total_symbols(settings):
                break
            if len(pf["watchlist"]) >= max_watchlist_size(settings, pf):
                break
            name = str(cand.get("name") or code)
            pf["watchlist"].append({"code": code, "name": name})
            changes.append(WatchlistChange("add", code, name, "早盘候选纳入观察池"))

    # Close: trim watchlist so holdings + watchlist (deduped) <= total cap
    pf["watchlist"] = _trim_by_score(
        pf["watchlist"],
        enriched,
        settings,
        max_watchlist_size(settings, pf),
        changes,
        base_mss=base_mss,
    )

    if verify and verify.get("verdict_current") == "回避":
        # Macro risk-off: keep only top 3 watchlist names
        pf["watchlist"] = _trim_by_score(
            pf["watchlist"],
            enriched,
            settings,
            min(3, max_watchlist_size(settings, pf)),
            changes,
            reason_prefix="宏观回避，收缩观察池",
            base_mss=base_mss,
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
    settings: dict[str, Any],
    limit: int,
    changes: list[WatchlistChange],
    *,
    reason_prefix: str = "超出上限，按评分保留",
    base_mss: Optional[float] = None,
) -> list[dict[str, Any]]:
    if len(watchlist) <= limit:
        return watchlist
    scored = [
        (
            _symbol_score(
                {**w, **enriched.get(_normalize_code(str(w.get("code", ""))), {})},
                base_mss=base_mss,
            ),
            w,
        )
        for w in watchlist
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    kept = [w for _, w in scored[:limit]]
    kept_codes = {_normalize_code(str(w.get("code", ""))) for w in kept}
    for w in watchlist:
        code = _normalize_code(str(w.get("code", "")))
        if code not in kept_codes:
            changes.append(
                WatchlistChange("remove", code, str(w.get("name", code)), reason_prefix)
            )
    return kept


def _snapshot_base_mss(snapshot: dict[str, Any], settings: dict[str, Any]) -> float:
    breakdown = snapshot.get("mss_breakdown") or {}
    if breakdown:
        from agent_reach.daily_run.verdict import compute_mss

        return float(compute_mss(breakdown, settings))
    return float(snapshot.get("mss_final") or 50)


def _symbol_score(row: dict[str, Any], *, base_mss: Optional[float] = None) -> float:
    base = float(base_mss if base_mss is not None else 50)
    chg = row.get("change_pct")
    if chg is not None:
        base += float(chg) * 0.5
    return base


def _has_code(watchlist: list[dict[str, Any]], code: str) -> bool:
    return any(_normalize_code(str(w.get("code", ""))) == code for w in watchlist)


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
    # Tail-read recent lines only (ledger grows append-only)
    raw = path.read_bytes()
    chunk = raw[-65536:] if len(raw) > 65536 else raw
    for line in chunk.decode("utf-8", errors="ignore").splitlines():
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
