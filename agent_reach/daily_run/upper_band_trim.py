# -*- coding: utf-8 -*-
"""Partial trim when price/MSS sits at week forecast upper band or before Kronos divergence day."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "near_upper_band_pct": 1.0,
    "sell_ratio": 0.30,
    "max_sell_ratio": 0.33,
    "max_shares": None,
    "once_per_symbol_per_day": True,
    "trigger_on_price_near_week_upper": True,
    "trigger_on_change_near_day_upper": True,
    "trigger_on_mss_near_forecast_upper": True,
    "mss_near_upper_pts": 2.0,
    "trigger_on_next_kronos_divergence_day": True,
}


def upper_band_trim_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    intraday = dict((settings or {}).get("intraday") or {})
    block = dict(intraday.get("upper_band_trim") or {})
    out = {**_DEFAULTS, **block}
    out["enabled"] = block.get("enabled", out.get("enabled", False)) is True
    return out


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holding_for_code(snapshot: dict[str, Any], code: Any) -> Optional[dict[str, Any]]:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return None
    for holding in (snapshot.get("portfolio") or {}).get("holdings") or []:
        if _normalize_code(str(holding.get("code", ""))) == norm:
            return holding
    return None


def _symbol_field(
    snapshot: dict[str, Any],
    code: Any,
    key: str,
    *,
    holding: Optional[dict[str, Any]] = None,
) -> Optional[float]:
    holding = holding or _holding_for_code(snapshot, code)
    if holding and holding.get(key) is not None:
        return _optional_float(holding[key])
    norm = _normalize_code(str(code or ""))
    if norm and _normalize_code(str(snapshot.get("code") or "")) == norm:
        return _optional_float(snapshot.get(key))
    for row in snapshot.get("symbols") or []:
        if _normalize_code(str(row.get("code", ""))) != norm:
            continue
        return _optional_float(row.get(key))
    return None


def _structured_symbol_pred(forecast: dict[str, Any], code: str) -> Optional[dict[str, Any]]:
    norm = _normalize_code(code)
    for row in (forecast.get("structured_predictions") or {}).get("symbols") or []:
        if _normalize_code(str(row.get("code") or "")) == norm:
            return row
    return None


def symbol_week_price_upper(
    code: str,
    forecast: dict[str, Any],
) -> Optional[float]:
    """Week Kronos/MC structured price_high for a symbol."""
    pred = _structured_symbol_pred(forecast, code)
    if pred:
        hi = _optional_float(pred.get("price_high"))
        if hi is not None:
            return hi
    sym = (forecast.get("symbols") or {}).get(_normalize_code(code)) or {}
    kronos = sym.get("kronos") or {}
    band = kronos.get("confidence_band") or []
    base = _optional_float(sym.get("base_price"))
    if base is None and pred:
        base = _optional_float(pred.get("base_price"))
    if base and isinstance(band, (list, tuple)) and len(band) >= 2:
        cum_hi = float(band[1])
        return round(base * (1 + cum_hi / 100.0), 2)
    return None


def symbol_day_change_upper(
    code: str,
    forecast: dict[str, Any],
    trading_day: str,
) -> Optional[float]:
    sym = (forecast.get("symbols") or {}).get(_normalize_code(code)) or {}
    day = (sym.get("days") or {}).get(trading_day) or {}
    rng = day.get("change_pct_range") or []
    if isinstance(rng, (list, tuple)) and len(rng) >= 2:
        return _optional_float(rng[1])
    k_day = ((sym.get("kronos") or {}).get("days") or {}).get(trading_day) or {}
    k_chg = _optional_float(k_day.get("change_pct"))
    if k_chg is not None:
        return k_chg + 0.5
    return None


def next_session_kronos_divergence_day(
    code: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    forecast: Optional[dict[str, Any]] = None,
) -> bool:
    from agent_reach.daily_run.trade_calendar import next_trading_day, today_shanghai
    from agent_reach.daily_run.week_forecast import load_active_forecast

    fc = forecast or load_active_forecast()
    if not fc:
        return False
    nxt = next_trading_day(today_shanghai(), settings=settings or {}).isoformat()
    sym = (fc.get("symbols") or {}).get(_normalize_code(code)) or {}
    return nxt in (sym.get("kronos_divergence_days") or [])


def _near_upper(actual: float, upper: float, band_pct: float) -> bool:
    if upper <= 0:
        return False
    floor_px = upper * (1.0 - float(band_pct) / 100.0)
    return float(actual) + 1e-9 >= floor_px


def _mss_near_forecast_upper(
    lookback_mss: Optional[float],
    settings: dict[str, Any],
    band_pts: float,
) -> tuple[bool, Optional[float]]:
    if lookback_mss is None:
        return False, None
    from agent_reach.daily_run.mss_forecast import active_day_mss_forecast_upper

    upper = active_day_mss_forecast_upper(settings)
    if upper is None:
        return False, None
    near = float(lookback_mss) + 1e-9 >= float(upper) - float(band_pts)
    return near, upper


def upper_band_trim_already_applied(
    prior_trades: Optional[list[dict[str, Any]]],
    code: Any,
) -> bool:
    norm = _normalize_code(str(code or ""))
    if not norm:
        return False
    for trade in prior_trades or []:
        if str(trade.get("action") or "") != "sell":
            continue
        if not trade.get("portfolio_applied"):
            continue
        if _normalize_code(str(trade.get("code") or "")) != norm:
            continue
        if trade.get("sell_kind") == "upper_band_trim" or "预测上沿止盈" in str(
            trade.get("reasoning") or ""
        ):
            return True
    return False


def resolve_upper_band_trim_triggers(
    settings: dict[str, Any],
    *,
    code: str,
    price: Optional[float],
    change_pct: Optional[float],
    lookback_mss: Optional[float],
    forecast: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Human-readable trigger tags (empty when none)."""
    cfg = upper_band_trim_cfg(settings)
    reasons: list[str] = []
    from agent_reach.daily_run.trade_calendar import today_shanghai
    from agent_reach.daily_run.week_forecast import load_active_forecast

    fc = forecast or load_active_forecast()
    if not fc:
        return reasons
    ds = today_shanghai().isoformat()
    band_pct = float(cfg.get("near_upper_band_pct", 1.0))

    if cfg.get("trigger_on_price_near_week_upper", True) and price is not None:
        upper_px = symbol_week_price_upper(code, fc)
        if upper_px is not None and _near_upper(float(price), float(upper_px), band_pct):
            reasons.append(f"现价 {price:.2f} 接近周预测上沿 {upper_px:.2f}（band {band_pct:.1f}%）")

    if cfg.get("trigger_on_change_near_day_upper", True) and change_pct is not None:
        chg_hi = symbol_day_change_upper(code, fc, ds)
        if chg_hi is not None and float(change_pct) + 1e-9 >= float(chg_hi) - band_pct:
            reasons.append(
                f"日涨幅 {change_pct:+.2f}% 接近当日预测上沿 {chg_hi:+.2f}%（band {band_pct:.1f}pp）"
            )

    if cfg.get("trigger_on_mss_near_forecast_upper", True):
        near_mss, mss_upper = _mss_near_forecast_upper(
            lookback_mss,
            settings,
            float(cfg.get("mss_near_upper_pts", 2.0)),
        )
        if near_mss and mss_upper is not None and lookback_mss is not None:
            reasons.append(
                f"Lookback MSS {lookback_mss:.0f} 接近当周 MSS 预测上沿 {mss_upper:.0f}"
            )

    if cfg.get("trigger_on_next_kronos_divergence_day", True) and next_session_kronos_divergence_day(
        code, settings=settings, forecast=fc
    ):
        reasons.append("次日为 Kronos 分歧日（forecast 标注）")

    return reasons


def upper_band_trim_effective_sell_ratio(
    settings: dict[str, Any],
    holding: dict[str, Any],
    *,
    base_ratio: float,
    sell_ratio_override: Optional[float] = None,
) -> float:
    cfg = upper_band_trim_cfg(settings)
    ratio = float(sell_ratio_override if sell_ratio_override is not None else cfg.get("sell_ratio", 0.30))
    ratio = min(ratio, float(cfg.get("max_sell_ratio", 0.33)))
    ratio = min(float(base_ratio), ratio)
    shares = int(holding.get("shares") or 0)
    max_sh = cfg.get("max_shares")
    if max_sh is not None and shares > 0:
        try:
            cap = int(max_sh) / shares
            ratio = min(ratio, max(0.0, cap))
        except (TypeError, ValueError):
            pass
    return ratio


def estimate_upper_band_trim_sell_shares(
    portfolio: dict[str, Any],
    code: str,
    settings: dict[str, Any],
    *,
    sell_ratio_override: Optional[float] = None,
) -> int:
    from agent_reach.daily_run.portfolio_manager import _min_lot, _round_lot

    norm = _normalize_code(code)
    shares = 0
    holding: dict[str, Any] = {}
    for row in portfolio.get("holdings") or []:
        if _normalize_code(str(row.get("code") or "")) == norm:
            shares = int(row.get("shares") or 0)
            holding = row
            break
    if shares <= 0:
        return 0
    cfg = upper_band_trim_cfg(settings)
    ratio = float(
        sell_ratio_override if sell_ratio_override is not None else cfg.get("sell_ratio", 0.30)
    )
    ratio = upper_band_trim_effective_sell_ratio(
        settings,
        holding,
        base_ratio=ratio,
        sell_ratio_override=ratio,
    )
    raw = int(shares * ratio)
    return min(shares, max(_round_lot(norm, raw), _min_lot(norm) if raw > 0 else 0))


def evaluate_upper_band_trim_sell(
    settings: dict[str, Any],
    *,
    report: dict[str, Any],
    snapshot: dict[str, Any],
    lookback_mss: float,
    prior_trades: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, Optional[str], Optional[float]]:
    """Return (allow_sell, hold_reason, sell_ratio)."""
    cfg = upper_band_trim_cfg(settings)
    if not cfg.get("enabled", False):
        return False, None, None

    code = report.get("code")
    holding = _holding_for_code(snapshot, code)
    if holding is None:
        return False, None, None

    if cfg.get("once_per_symbol_per_day", True) and upper_band_trim_already_applied(
        prior_trades, code
    ):
        return False, "今日已执行预测上沿止盈减仓，同标的不再重复", None

    price = _symbol_field(snapshot, code, "price", holding=holding)
    change_pct = _symbol_field(snapshot, code, "change_pct", holding=holding)
    triggers = resolve_upper_band_trim_triggers(
        settings,
        code=str(code or ""),
        price=price,
        change_pct=change_pct,
        lookback_mss=lookback_mss,
    )
    if not triggers:
        return False, None, None

    ratio = upper_band_trim_effective_sell_ratio(
        settings,
        holding,
        base_ratio=float(cfg.get("max_sell_ratio", 0.33)),
    )
    head = "；".join(triggers)
    reason = f"预测上沿/分歧日防御减仓：{head}（sell_ratio≈{ratio:.0%}）"
    return True, reason, ratio