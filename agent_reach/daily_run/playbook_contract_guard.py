# -*- coding: utf-8
"""Playbook contract guards: morning handoff + settings → buy/sell apply blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code


@dataclass(frozen=True)
class PlaybookBlock:
    reason: str
    block_kind: str


def playbook_contract_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("playbook_contract") or {})
    symbols = dict(raw.get("symbols") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "require_morning_handoff": raw.get("require_morning_handoff", True) is not False,
        "total_stock_weight_cap_pct": float(raw.get("total_stock_weight_cap_pct") or 37.0),
        "target_tolerance_pp": float(raw.get("target_tolerance_pp") or 2.0),
        "watchlist_buy_codes": [
            _normalize_code(str(c)) for c in (raw.get("watchlist_buy_codes") or ["603986"]) if str(c).strip()
        ],
        "symbols": symbols,
        "hard_stop_prices": {
            _normalize_code(str(k)): float(v)
            for k, v in (raw.get("hard_stop_prices") or {}).items()
            if str(k).strip()
        },
        "block_add_operations": tuple(
            str(x) for x in (raw.get("block_add_operations") or ["持有", "观望"])
        ),
    }


def playbook_contract_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    return playbook_contract_cfg(settings)["enabled"]


def _morning_handoff_loaded() -> Optional[dict[str, Any]]:
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        flag = os.environ.get("AGENT_REACH_PLAYBOOK_USE_HANDOFF", "").strip().lower()
        if flag not in ("1", "true", "yes"):
            return None
    try:
        from agent_reach.daily_run.close_morning_handoff import load_morning_handoff

        return load_morning_handoff()
    except Exception:
        return None


def playbook_contract_active(settings: Optional[dict[str, Any]] = None) -> bool:
    """Guard is on when enabled and (optionally) today's morning handoff exists."""
    cfg = playbook_contract_cfg(settings)
    if not cfg["enabled"]:
        return False
    if cfg["require_morning_handoff"] and not _morning_handoff_loaded():
        return False
    return True


def _parse_weight_from_label(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _morning_contract_row(code: str, settings: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    handoff = _morning_handoff_loaded()
    if not handoff:
        return None
    norm = _normalize_code(code)
    for row in handoff.get("action_checklist") or []:
        if not isinstance(row, dict):
            continue
        if _normalize_code(str(row.get("code") or "")) == norm:
            return row
    return None


def resolve_symbol_contract(
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge static settings symbol rules with today's morning handoff row."""
    cfg = playbook_contract_cfg(settings)
    norm = _normalize_code(code)
    static = dict(cfg["symbols"].get(norm) or cfg["symbols"].get(code) or {})
    row = _morning_contract_row(norm, settings) or {}

    operation = str(row.get("operation") or static.get("operation") or "").strip()
    target_weight = row.get("target_weight_pct")
    if target_weight is None:
        target_weight = static.get("target_weight_pct")
    if target_weight is None:
        target_weight = _parse_weight_from_label(str(row.get("target_position") or ""))
    if target_weight is None:
        target_weight = _parse_weight_from_label(str(static.get("target_position") or ""))

    min_weight = static.get("min_weight_pct")
    max_weight = static.get("max_weight_pct")
    block_add = static.get("block_add")
    if block_add is None and operation in cfg["block_add_operations"]:
        block_add = True
    if block_add is None:
        block_add = False

    return {
        "code": norm,
        "operation": operation,
        "target_weight_pct": _optional_float(target_weight),
        "min_weight_pct": _optional_float(min_weight),
        "max_weight_pct": _optional_float(max_weight),
        "block_add": bool(block_add),
        "hard_stop_price": cfg["hard_stop_prices"].get(norm),
        "watchlist_buy_allowed": norm in cfg["watchlist_buy_codes"],
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _portfolio_total(portfolio: dict[str, Any]) -> float:
    from agent_reach.daily_run.morning_cards import _portfolio_total as total_fn

    return float(total_fn(portfolio) or 0.0)


def stock_weight_pct(portfolio: dict[str, Any]) -> float:
    total = _portfolio_total(portfolio)
    if total <= 0:
        return 0.0
    mv = 0.0
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        shares = int(row.get("shares") or 0)
        price = row.get("price") or row.get("cost")
        if shares <= 0 or price is None:
            continue
        try:
            mv += shares * float(price)
        except (TypeError, ValueError):
            continue
    return round(mv / total * 100.0, 2)


def holding_weight_pct(
    portfolio: dict[str, Any],
    code: str,
    *,
    price_override: Optional[float] = None,
) -> Optional[float]:
    norm = _normalize_code(code)
    for row in portfolio.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) != norm:
            continue
        holding = dict(row)
        if price_override is not None:
            holding["price"] = price_override
        from agent_reach.daily_run.morning_cards import _holding_weight_pct

        return _holding_weight_pct(holding, portfolio)
    return 0.0


def _estimate_buy_shares(
    portfolio: dict[str, Any],
    enriched: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    *,
    code: str,
    cash_limit_bypass: bool = False,
    max_position_pct_override: Optional[float] = None,
) -> int:
    from agent_reach.daily_run.portfolio_manager import simulate_buy_analysis

    analysis = simulate_buy_analysis(
        portfolio,
        enriched,
        settings,
        prefer_code=code,
        cash_limit_bypass=cash_limit_bypass,
        max_position_pct_override=max_position_pct_override,
    )
    shares = int(analysis.get("buy_shares") or 0)
    if shares > 0:
        return shares
    return 0


def _project_weight_after_trade(
    portfolio: dict[str, Any],
    *,
    code: str,
    price: float,
    delta_shares: int,
) -> Optional[float]:
    total = _portfolio_total(portfolio)
    if total <= 0 or price <= 0:
        return None
    norm = _normalize_code(code)
    current_shares = 0
    other_mv = 0.0
    for row in portfolio.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        shares = int(row.get("shares") or 0)
        px = row.get("price") or row.get("cost") or 0
        try:
            px_f = float(px)
        except (TypeError, ValueError):
            continue
        if _normalize_code(str(row.get("code") or "")) == norm:
            current_shares = shares
        else:
            other_mv += shares * px_f
    new_shares = max(0, current_shares + delta_shares)
    new_total = total  # approximate: cash/stock shift within same NAV
    new_mv = other_mv + new_shares * price
    return round(new_mv / new_total * 100.0, 2) if new_total > 0 else None


def _project_stock_weight_after_buy(
    portfolio: dict[str, Any],
    *,
    code: str,
    price: float,
    buy_shares: int,
    buy_notional: float,
) -> Optional[float]:
    current = stock_weight_pct(portfolio)
    total = _portfolio_total(portfolio)
    if total <= 0:
        return None
    # Stock MV increases by buy_notional; cash decreases; total NAV unchanged in paper sim.
    current_mv = total * current / 100.0
    return round((current_mv + buy_notional) / total * 100.0, 2)


def playbook_contract_buy_block(
    *,
    settings: dict[str, Any],
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    enriched: Optional[dict[str, dict[str, Any]]] = None,
    code: str,
    cash_limit_bypass: bool = False,
    max_position_pct_override: Optional[float] = None,
) -> Optional[PlaybookBlock]:
    if not playbook_contract_enabled(settings):
        return None

    cfg = playbook_contract_cfg(settings)
    norm = _normalize_code(code)
    contract = resolve_symbol_contract(norm, settings=settings)
    session_active = playbook_contract_active(settings)

    from agent_reach.daily_run.portfolio_manager import _symbol_is_holding

    is_holding = _symbol_is_holding(norm, portfolio)
    in_watchlist = any(
        _normalize_code(str(w.get("code") or "")) == norm for w in (portfolio.get("watchlist") or [])
    )

    if session_active:
        if not is_holding and not in_watchlist and not contract["watchlist_buy_allowed"]:
            return PlaybookBlock(
                reason=f"Playbook 契约：{norm} 非观察池加仓标的，禁止新建仓",
                block_kind="playbook_no_add",
            )

        if is_holding and contract["block_add"]:
            return PlaybookBlock(
                reason=(
                    f"Playbook 契约：{norm} 今日计划「{contract['operation'] or '持有'}」，"
                    "禁止加仓"
                ),
                block_kind="playbook_no_add",
            )

    if not enriched:
        from agent_reach.daily_run.symbols import build_enriched_symbols

        enriched = build_enriched_symbols(snapshot)

    price_raw = (enriched.get(norm) or {}).get("price") or snapshot.get("price")
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    buy_shares = _estimate_buy_shares(
        portfolio,
        enriched,
        settings,
        code=norm,
        cash_limit_bypass=cash_limit_bypass,
        max_position_pct_override=max_position_pct_override,
    )
    if buy_shares <= 0:
        return None

    buy_notional = buy_shares * price
    tol = cfg["target_tolerance_pp"]

    if session_active:
        post_weight = _project_weight_after_trade(
            portfolio,
            code=norm,
            price=price,
            delta_shares=buy_shares,
        )
        ceiling = contract.get("max_weight_pct")
        if ceiling is None and contract.get("target_weight_pct") is not None:
            ceiling = float(contract["target_weight_pct"]) + tol
        if ceiling is not None and post_weight is not None and post_weight > float(ceiling) + 0.05:
            return PlaybookBlock(
                reason=(
                    f"Playbook 契约：{norm} 加仓后权重预计 {post_weight:.1f}%"
                    f" > 上限 {float(ceiling):.1f}%"
                ),
                block_kind="playbook_weight_ceiling",
            )

        post_stock = _project_stock_weight_after_buy(
            portfolio,
            code=norm,
            price=price,
            buy_shares=buy_shares,
            buy_notional=buy_notional,
        )
        cap = cfg["total_stock_weight_cap_pct"]
        if post_stock is not None and post_stock > cap + 0.05:
            return PlaybookBlock(
                reason=(
                    f"Playbook 契约：加仓后总股票仓位预计 {post_stock:.1f}%"
                    f" > 上限 {cap:.1f}%"
                ),
                block_kind="playbook_total_cap",
            )

    return None


def playbook_contract_sell_block(
    *,
    settings: dict[str, Any],
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    code: str,
    sell_shares: int,
    sell_kind: Optional[str] = None,
    price: Optional[float] = None,
) -> Optional[PlaybookBlock]:
    if not playbook_contract_enabled(settings):
        return None
    if sell_shares <= 0:
        return None
    if sell_kind not in (None, "defensive_trim", "partial_sell"):
        return None

    norm = _normalize_code(code)
    contract = resolve_symbol_contract(norm, settings=settings)
    floor = contract.get("min_weight_pct")
    if floor is None:
        return None

    if price is None:
        price = _optional_float(snapshot.get("price"))
    if price is None or price <= 0:
        return None

    hard_stop = contract.get("hard_stop_price")
    if hard_stop is not None and price <= float(hard_stop):
        return None

    post_weight = _project_weight_after_trade(
        portfolio,
        code=norm,
        price=price,
        delta_shares=-sell_shares,
    )
    if post_weight is not None and post_weight + 0.05 < float(floor):
        return PlaybookBlock(
            reason=(
                f"Playbook 契约：{norm} 卖后权重预计 {post_weight:.1f}%"
                f" < 下限 {float(floor):.1f}%（硬止损 {hard_stop or '—'} 除外）"
            ),
            block_kind="playbook_weight_floor",
        )
    return None


def playbook_contract_buy_block_reason(
    *,
    settings: dict[str, Any],
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    enriched: Optional[dict[str, dict[str, Any]]] = None,
    code: str,
    cash_limit_bypass: bool = False,
    max_position_pct_override: Optional[float] = None,
) -> Optional[str]:
    block = playbook_contract_buy_block(
        settings=settings,
        portfolio=portfolio,
        snapshot=snapshot,
        enriched=enriched,
        code=code,
        cash_limit_bypass=cash_limit_bypass,
        max_position_pct_override=max_position_pct_override,
    )
    return block.reason if block else None


def estimate_defensive_trim_sell_shares(
    portfolio: dict[str, Any],
    code: str,
    settings: dict[str, Any],
    *,
    sell_ratio_override: Optional[float] = None,
) -> int:
    """Rough share count for playbook floor precheck (matches ~memory_sell_ratio trim)."""
    from agent_reach.daily_run.defensive_trim_guards import defensive_trim_cfg

    norm = _normalize_code(code)
    shares = 0
    for row in portfolio.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) == norm:
            shares = int(row.get("shares") or 0)
            break
    if shares <= 0:
        return 0
    cfg = defensive_trim_cfg(settings)
    ratio = float(sell_ratio_override if sell_ratio_override is not None else cfg.get("memory_sell_ratio") or 0.35)
    ratio = max(0.05, min(1.0, ratio))
    from agent_reach.daily_run.portfolio_manager import _min_lot, _round_lot

    raw = int(shares * ratio)
    return min(shares, max(_round_lot(norm, raw), _min_lot(norm) if raw > 0 else 0))


def playbook_contract_sell_block_reason(
    *,
    settings: dict[str, Any],
    portfolio: dict[str, Any],
    snapshot: dict[str, Any],
    code: str,
    sell_shares: int,
    sell_kind: Optional[str] = None,
    price: Optional[float] = None,
) -> Optional[str]:
    block = playbook_contract_sell_block(
        settings=settings,
        portfolio=portfolio,
        snapshot=snapshot,
        code=code,
        sell_shares=sell_shares,
        sell_kind=sell_kind,
        price=price,
    )
    return block.reason if block else None
