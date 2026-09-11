# -*- coding: utf-8
"""Execution quality metrics (Qlib indicator_analysis inspired: PA / FFR / POS)."""

from __future__ import annotations

from typing import Any, Optional


def execution_quality_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("execution_quality") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "min_fill_rate": float(block.get("min_fill_rate", 0.95)),
        "warn_slippage_bps": float(block.get("warn_slippage_bps", 15.0)),
    }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_fill_rate(trade: dict[str, Any]) -> Optional[float]:
    requested = _optional_float(trade.get("requested_shares") or trade.get("shares"))
    filled = _optional_float(trade.get("filled_shares") or trade.get("deal_shares"))
    if requested is None or requested <= 0:
        actions = trade.get("portfolio_actions") or []
        if actions and trade.get("portfolio_applied"):
            return 1.0
        if trade.get("portfolio_applied") is False:
            return 0.0
        return None
    if filled is None:
        filled = requested if trade.get("portfolio_applied") else 0.0
    return max(0.0, min(1.0, filled / requested))


def _trade_price_advantage_bps(trade: dict[str, Any]) -> Optional[float]:
    signal_px = _optional_float(trade.get("signal_price") or trade.get("reference_price"))
    exec_px = _optional_float(trade.get("execution_price") or trade.get("fill_price"))
    if signal_px is None or exec_px is None or signal_px <= 0:
        meta = trade.get("execution_meta") or {}
        exec_px = exec_px or _optional_float(meta.get("price"))
        signal_px = signal_px or _optional_float(meta.get("reference_price"))
    if signal_px is None or exec_px is None or signal_px <= 0:
        return None
    side = str(trade.get("action") or "").lower()
    if side == "buy":
        return (signal_px - exec_px) / signal_px * 10000.0
    if side == "sell":
        return (exec_px - signal_px) / signal_px * 10000.0
    return None


def compute_execution_quality(
    trades: list[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = execution_quality_cfg(settings)
    if not cfg["enabled"]:
        return {"skipped": True, "enabled": False}

    rows = [t for t in trades if isinstance(t, dict) and str(t.get("action") or "").lower() in {"buy", "sell"}]
    if not rows:
        return {
            "skipped": False,
            "trade_count": 0,
            "fill_rate": None,
            "price_advantage_bps": None,
            "positive_rate_pct": None,
            "warnings": [],
        }

    fill_rates: list[float] = []
    pa_bps: list[float] = []
    wins = 0
    evaluated = 0
    warnings: list[str] = []

    for trade in rows:
        fr = _trade_fill_rate(trade)
        if fr is not None:
            fill_rates.append(fr)
        pa = _trade_price_advantage_bps(trade)
        if pa is not None:
            pa_bps.append(pa)
        pnl = _optional_float(trade.get("realized_pnl"))
        if pnl is not None:
            evaluated += 1
            if pnl > 0:
                wins += 1

    fill_rate = round(sum(fill_rates) / len(fill_rates), 4) if fill_rates else None
    pa_mean = round(sum(pa_bps) / len(pa_bps), 2) if pa_bps else None
    pos_rate = round(wins / evaluated * 100.0, 1) if evaluated else None

    if fill_rate is not None and fill_rate < cfg["min_fill_rate"]:
        warnings.append(f"FFR {fill_rate:.0%} 低于阈值 {cfg['min_fill_rate']:.0%}")
    if pa_mean is not None and pa_mean < -cfg["warn_slippage_bps"]:
        warnings.append(f"PA {pa_mean:.1f}bps 劣于阈值 -{cfg['warn_slippage_bps']:.0f}bps")

    return {
        "skipped": False,
        "trade_count": len(rows),
        "fill_rate": fill_rate,
        "price_advantage_bps": pa_mean,
        "positive_rate_pct": pos_rate,
        "warnings": warnings,
        "metrics": {
            "ffr": fill_rate,
            "pa": pa_mean,
            "pos": pos_rate,
        },
    }


def enrich_trade_execution_quality(
    trade_record: dict[str, Any],
    *,
    apply_result: Any = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not execution_quality_cfg(settings).get("enabled"):
        return trade_record
    meta = dict(trade_record.get("execution_meta") or {})
    if apply_result is not None:
        for key in ("price", "reference_price", "fill_timing", "slippage_rate"):
            val = getattr(apply_result, key, None)
            if val is None and hasattr(apply_result, "execution_meta"):
                em = getattr(apply_result, "execution_meta") or {}
                val = em.get(key) if isinstance(em, dict) else None
            if val is not None:
                meta[key] = val
    trade_record["execution_meta"] = meta
    fr = _trade_fill_rate(trade_record)
    pa = _trade_price_advantage_bps(trade_record)
    if fr is not None:
        trade_record["fill_rate"] = fr
    if pa is not None:
        trade_record["price_advantage_bps"] = round(pa, 2)
    return trade_record


def render_execution_quality_markdown(result: dict[str, Any]) -> str:
    if result.get("skipped"):
        return "## Execution Quality\n\n已跳过。"
    lines = ["## Execution Quality (PA / FFR / POS)", ""]
    lines.append(f"- 成交笔数：**{result.get('trade_count', 0)}**")
    if result.get("fill_rate") is not None:
        lines.append(f"- FFR（成交率）：**{float(result['fill_rate']):.1%}**")
    if result.get("price_advantage_bps") is not None:
        lines.append(f"- PA（价格优势）：**{float(result['price_advantage_bps']):+.1f} bps**")
    if result.get("positive_rate_pct") is not None:
        lines.append(f"- POS（盈利占比）：**{float(result['positive_rate_pct']):.1f}%**")
    for warn in result.get("warnings") or []:
        lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)
