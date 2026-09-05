# -*- coding: utf-8
"""Cross-day session seed, rolling buy what-if gates, overlay walk-forward hints."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.trade_calendar import today_shanghai


def quant_calibration_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict((settings or {}).get("quant_calibration") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "rolling_window_days": int(raw.get("rolling_window_days", 5)),
        "walkforward_window_days": int(raw.get("walkforward_window_days", 10)),
        "apply_walkforward_overlay": raw.get("apply_walkforward_overlay", True) is not False,
        "rolling_mtm_gate_enabled": raw.get("rolling_mtm_gate_enabled", True) is not False,
        "rolling_mtm_min_sum": float(raw.get("rolling_mtm_min_sum", 0.0)),
        "loss_pct_defensive": float(raw.get("loss_pct_defensive", -0.15)),
        "supportive_pnl_pct": float(raw.get("supportive_pnl_pct", 0.1)),
        "friction_buy_multiplier": float(raw.get("friction_buy_multiplier", 1.25)),
        "friction_block_buys": raw.get("friction_block_buys", True) is not False,
        "forecast_hit_rate_min": float(raw.get("forecast_hit_rate_min", 0.45)),
        "forecast_hit_rate_gate_enabled": raw.get("forecast_hit_rate_gate_enabled", True) is not False,
    }


def _handoff_dir() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "handoff"


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _defensive_trim_active(settings: Optional[dict[str, Any]]) -> bool:
    runtime = (settings or {}).get("harness_runtime") or {}
    signals = runtime.get("trade_signals") or {}
    return bool(signals.get("defensive_trim"))


def classify_close_session_regime(
    *,
    daily_pnl: Optional[float],
    daily_pnl_pct: Optional[float],
    defensive_trim: bool,
    cfg: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if defensive_trim:
        reasons.append("收盘 defensive_trim active")
    if daily_pnl is not None and float(daily_pnl) < 0:
        reasons.append(f"当日组合净值亏损（{float(daily_pnl):+,.0f}）")
    if daily_pnl_pct is not None and float(daily_pnl_pct) <= cfg["loss_pct_defensive"]:
        reasons.append(f"当日收益率 {float(daily_pnl_pct):+.2f}%")

    if reasons:
        return "defensive", reasons

    if (
        daily_pnl is not None
        and float(daily_pnl) > 0
        and not defensive_trim
        and (daily_pnl_pct is None or float(daily_pnl_pct) >= cfg["supportive_pnl_pct"])
    ):
        return "supportive", ["当日盈利且未触发 defensive_trim"]
    return "neutral", ["收盘状态中性"]


def merge_session_regime(computed: str, seed_regime: Optional[str]) -> str:
    if not seed_regime:
        return computed
    if computed == "defensive" or seed_regime == "defensive":
        return "defensive"
    if computed == "neutral" and seed_regime == "supportive":
        return "supportive"
    return computed


def load_close_handoff_history(
    *,
    end_day: Optional[date] = None,
    window_days: int = 10,
    settings: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    from agent_reach.daily_run.prior_close import prev_trading_day

    end = end_day or today_shanghai()
    out: list[dict[str, Any]] = []
    day = end
    for _ in range(max(1, window_days) * 3):
        if len(out) >= window_days:
            break
        path = _handoff_dir() / f"close_{day.isoformat()}.json"
        payload = _read_json(path)
        if payload:
            out.append(payload)
        nxt = prev_trading_day(day, settings=settings or {})
        if nxt >= day:
            break
        day = nxt
    return out


def compute_rolling_buy_stats(
    history: list[dict[str, Any]],
    *,
    window_days: int,
) -> dict[str, Any]:
    mtm_vals: list[float] = []
    pnl_vals: list[float] = []
    loss_days = 0
    for row in history[:window_days]:
        seed = row.get("next_day_session_seed") or {}
        buy = seed.get("buy_whatif") or {}
        mtm = _optional_float(buy.get("baseline_excess_buy_mtm_pnl"))
        if mtm is not None:
            mtm_vals.append(mtm)
        pnl = _optional_float(seed.get("daily_pnl"))
        if pnl is not None:
            pnl_vals.append(pnl)
            if pnl < 0:
                loss_days += 1
    return {
        "window_days": min(window_days, len(history)),
        "mtm_sum": round(sum(mtm_vals), 2) if mtm_vals else 0.0,
        "mtm_days": len(mtm_vals),
        "pnl_sum": round(sum(pnl_vals), 2) if pnl_vals else 0.0,
        "loss_days": loss_days,
    }


def recommend_overlay_deltas(
    history: list[dict[str, Any]],
    *,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rolling = compute_rolling_buy_stats(history, window_days=cfg["walkforward_window_days"])
    loss_days = int(rolling.get("loss_days") or 0)
    pnl_sum = float(rolling.get("pnl_sum") or 0)
    mtm_sum = float(rolling.get("mtm_sum") or 0)

    if loss_days >= 3 or pnl_sum < 0:
        agg = 3.0
        macro = 2.5
        every_n = 1
    elif pnl_sum > 0 and mtm_sum > 500:
        agg = 1.0
        macro = 1.0
        every_n = 0
    else:
        agg = 2.0
        macro = 2.0
        every_n = 1

    return {
        "morning_open": {
            "aggressive_entry_delta": agg,
            "macro_veto_delta": macro,
            "trade_every_n_delta": every_n,
        },
        "pm_session": {
            "aggressive_entry_delta": agg + 0.5,
            "macro_veto_delta": macro,
            "trade_every_n_delta": every_n,
        },
        "basis": {
            "loss_days": loss_days,
            "pnl_sum": pnl_sum,
            "mtm_sum": mtm_sum,
        },
    }


def build_next_day_session_seed(
    *,
    portfolio_summary: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    close_day: Optional[date] = None,
) -> dict[str, Any]:
    cfg = quant_calibration_cfg(settings)
    summary = portfolio_summary or {}
    close = close_day or today_shanghai()
    daily_pnl = _optional_float(summary.get("daily_pnl"))
    daily_pnl_pct = _optional_float(summary.get("daily_pnl_pct"))
    buy_raw = summary.get("buy_rules_whatif")
    buy_whatif: dict[str, Any] = {}
    if isinstance(buy_raw, dict):
        buy_whatif = {
            "baseline_excess_buy_mtm_pnl": _optional_float(buy_raw.get("baseline_excess_buy_mtm_pnl")),
            "buy_notional_delta": _optional_float(buy_raw.get("buy_notional_delta")),
        }
    elif hasattr(buy_raw, "baseline_excess_buy_mtm_pnl"):
        buy_whatif = {
            "baseline_excess_buy_mtm_pnl": _optional_float(getattr(buy_raw, "baseline_excess_buy_mtm_pnl", None)),
            "buy_notional_delta": _optional_float(getattr(buy_raw, "buy_notional_delta", None)),
        }

    defensive_trim = _defensive_trim_active(settings)
    regime, reasons = classify_close_session_regime(
        daily_pnl=daily_pnl,
        daily_pnl_pct=daily_pnl_pct,
        defensive_trim=defensive_trim,
        cfg=cfg,
    )
    history = load_close_handoff_history(
        end_day=close,
        window_days=cfg["walkforward_window_days"],
        settings=settings,
    )
    rolling = compute_rolling_buy_stats(history, window_days=cfg["rolling_window_days"])
    overlay_recommendation = recommend_overlay_deltas(history, cfg=cfg)

    return {
        "close_date": close.isoformat(),
        "regime": regime,
        "reasons": reasons,
        "defensive_trim": defensive_trim,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
        "buy_whatif": buy_whatif,
        "rolling": rolling,
        "overlay_recommendation": overlay_recommendation,
        "enabled": cfg["enabled"],
    }


def load_prior_close_session_seed(
    *,
    for_day: Optional[date] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    from agent_reach.daily_run.close_morning_handoff import load_close_handoff
    from agent_reach.daily_run.prior_close import prev_trading_day

    day = for_day or today_shanghai()
    prior = prev_trading_day(day, settings=settings or {})
    handoff = load_close_handoff(close_day=prior, settings=settings)
    if not handoff:
        return None
    block = handoff.get("next_day_session_seed")
    return dict(block) if isinstance(block, dict) else None


def effective_overlay_deltas(
    block_name: str,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge static config deltas with prior-close walk-forward recommendation."""
    cfg = quant_calibration_cfg(settings)
    if block_name == "morning_open":
        from agent_reach.daily_run.am_open_overlay import am_open_cfg

        base = am_open_cfg(settings)
    else:
        from agent_reach.daily_run.pm_session_overlay import pm_session_cfg

        base = pm_session_cfg(settings)

    out = {
        "aggressive_entry_delta": float(base["aggressive_entry_delta"]),
        "macro_veto_delta": float(base["macro_veto_delta"]),
        "trade_every_n_delta": int(base["trade_every_n_delta"]),
        "supportive_aggressive_entry_delta": float(base["supportive_aggressive_entry_delta"]),
        "supportive_trade_every_n_delta": int(base["supportive_trade_every_n_delta"]),
    }
    if not cfg["enabled"] or not cfg["apply_walkforward_overlay"]:
        return out

    seed = load_prior_close_session_seed(settings=settings)
    if not seed or seed.get("enabled") is False:
        return out
    rec = (seed.get("overlay_recommendation") or {}).get(block_name) or {}
    for key in ("aggressive_entry_delta", "macro_veto_delta"):
        if key in rec:
            out[key] = float(rec[key])
    if "trade_every_n_delta" in rec:
        out["trade_every_n_delta"] = int(rec["trade_every_n_delta"])
    return out


def rolling_buy_mtm_gate(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return (passes, detail) for deploy step-up rolling MTM gate."""
    cfg = quant_calibration_cfg(settings)
    if not cfg["enabled"] or not cfg["rolling_mtm_gate_enabled"]:
        return True, ""
    seed = load_prior_close_session_seed(settings=settings)
    if not seed:
        return True, ""
    rolling = seed.get("rolling") or {}
    mtm_sum = _optional_float(rolling.get("mtm_sum"))
    if mtm_sum is None:
        return True, ""
    if float(mtm_sum) <= cfg["rolling_mtm_min_sum"]:
        days = int(rolling.get("window_days") or 0)
        return False, f"滚动{days}日少买MTM合计 {float(mtm_sum):+,.0f} 未验证加仓机会"
    return True, ""


def forecast_hit_rate_gate(
    *,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Block deploy step-up when rolling forecast symbol hit rate is too low."""
    cfg = quant_calibration_cfg(settings)
    if not cfg["enabled"] or not cfg["forecast_hit_rate_gate_enabled"]:
        return True, ""
    from agent_reach.daily_run.week_forecast import load_calibration_file

    cal = load_calibration_file()
    hit_rate = _optional_float(cal.get("hit_rate"))
    if hit_rate is None:
        return True, ""
    if float(hit_rate) < cfg["forecast_hit_rate_min"]:
        return False, (
            f"预测滚动命中率 {float(hit_rate):.0%} 低于 {cfg['forecast_hit_rate_min']:.0%}，"
            "禁止 deploy step-up"
        )
    return True, ""


def friction_buy_blocked(expected_return_pct: float, settings: dict[str, Any]) -> bool:
    from agent_reach.daily_run.intraday_policy import effective_friction_hurdle

    cfg = quant_calibration_cfg(settings)
    raw = (settings or {}).get("quant_calibration")
    multiplier = cfg["friction_buy_multiplier"] if raw is not None else 1.0
    if not cfg["friction_block_buys"]:
        return False
    hurdle = effective_friction_hurdle(settings) * multiplier
    return float(expected_return_pct) <= hurdle


def walkforward_report(*, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = quant_calibration_cfg(settings)
    history = load_close_handoff_history(
        window_days=cfg["walkforward_window_days"],
        settings=settings,
    )
    rolling = compute_rolling_buy_stats(history, window_days=cfg["rolling_window_days"])
    recommendation = recommend_overlay_deltas(history, cfg=cfg)
    prior_seed = load_prior_close_session_seed(settings=settings)
    return {
        "history_days": len(history),
        "rolling": rolling,
        "overlay_recommendation": recommendation,
        "prior_close_seed": prior_seed,
        "effective_morning_open": effective_overlay_deltas("morning_open", settings=settings),
        "effective_pm_session": effective_overlay_deltas("pm_session", settings=settings),
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from agent_reach.daily_run.settings import load_settings

    parser = argparse.ArgumentParser(description="Overlay walk-forward calibration report")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args(argv)
    report = walkforward_report(settings=load_settings())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        rec = report["overlay_recommendation"]
        basis = rec.get("basis") or {}
        print("Overlay walk-forward (prior close handoffs)")
        print(f"  history_days: {report['history_days']}")
        print(f"  rolling mtm_sum: {report['rolling'].get('mtm_sum')} loss_days: {report['rolling'].get('loss_days')}")
        print(f"  basis: pnl_sum={basis.get('pnl_sum')} mtm_sum={basis.get('mtm_sum')}")
        print(f"  morning_open: {rec.get('morning_open')}")
        print(f"  pm_session: {rec.get('pm_session')}")
        print(f"  effective morning: {report['effective_morning_open']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
