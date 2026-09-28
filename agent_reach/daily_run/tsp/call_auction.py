# -*- coding: utf-8 -*-
"""TSP 9:25 Call Auction Imbalance & Divergence Sentinel.

Performs 9:25 AM call auction order-flow analysis adapted from Tick Stock Panel:
1. Call Auction Explosive Volume (爆量抢筹 / 弱转强):
   - Auction volume ratio >= 3.0% of yesterday's total volume.
   - Open change >= +1.5% (unexpected higher open / aggressive bidding).
   - Signals institutional/hot-money accumulation (+8.0 MSS boost).

2. Panic Dumping / Floor Open (核按钮 / 强转弱):
   - Open change <= -4.0% (following strong close or limit up), or <= -7.0% (near limit down).
   - Signals severe distribution / panic dumping.
   - Triggers buy veto (blocked_buy = True, -15.0 MSS delta).
"""

from __future__ import annotations

from typing import Any, Optional
from loguru import logger

from agent_reach.daily_run.tsp.config import tsp_quant_cfg


def evaluate_call_auction_divergence(
    symbol_code: str,
    symbol_data: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate 9:25 call auction divergence for a stock symbol.

    Args:
        symbol_code: Stock code (e.g. "688008" or "SH688008").
        symbol_data: Dictionary containing snapshot, quote, or report details.
        settings: Optional daily-run settings override.

    Returns:
        Dict with keys:
        - symbol: str
        - signal: "weak_to_strong" | "panic_dumping" | "normal"
        - open_pct: float
        - auction_ratio_pct: float
        - is_weak_to_strong: bool
        - is_panic_dumping: bool
        - blocked_buy: bool
        - mss_delta: float
        - reason: str
    """
    cfg = tsp_quant_cfg(settings)
    auction_cfg = cfg.get("call_auction") or {}
    enabled = cfg.get("enabled", True) and auction_cfg.get("enabled", True)

    default_result: dict[str, Any] = {
        "symbol": str(symbol_code or ""),
        "signal": "normal",
        "open_pct": 0.0,
        "auction_ratio_pct": 0.0,
        "is_weak_to_strong": False,
        "is_panic_dumping": False,
        "blocked_buy": False,
        "mss_delta": 0.0,
        "reason": "",
    }

    if not enabled or not symbol_data:
        return default_result

    try:
        data = dict(symbol_data)
        if isinstance(data.get("snapshot"), dict):
            data.update(data["snapshot"])
        if isinstance(data.get("report"), dict):
            data.update(data["report"])

        # 1. Extract open price & prev close
        open_price = float(data.get("open") or data.get("open_price") or 0.0)
        prev_close = float(
            data.get("prev_close")
            or data.get("last_close")
            or data.get("close_prev")
            or data.get("pre_close")
            or 0.0
        )

        if prev_close > 0 and open_price > 0:
            open_pct = round(((open_price / prev_close) - 1.0) * 100.0, 2)
        else:
            open_pct = float(data.get("open_pct") or data.get("open_change_pct") or 0.0)

        # 2. Extract call auction volume / turnover ratio
        auction_amt = float(data.get("auction_amount") or data.get("call_auction_amount") or 0.0)
        yest_amt = float(
            data.get("yesterday_amount")
            or data.get("prev_amount")
            or data.get("amount_prev")
            or 0.0
        )

        auction_vol = float(data.get("auction_volume") or data.get("call_auction_vol") or 0.0)
        yest_vol = float(
            data.get("yesterday_volume")
            or data.get("prev_volume")
            or data.get("vol_prev")
            or 0.0
        )

        if auction_amt > 0 and yest_amt > 0:
            auction_ratio_pct = round((auction_amt / yest_amt) * 100.0, 2)
        elif auction_vol > 0 and yest_vol > 0:
            auction_ratio_pct = round((auction_vol / yest_vol) * 100.0, 2)
        else:
            auction_ratio_pct = float(
                data.get("auction_ratio_pct") or data.get("auction_ratio") or 0.0
            )

        # 3. Threshold configurations
        panic_threshold = float(auction_cfg.get("panic_open_pct", -4.0))
        extreme_panic_threshold = float(auction_cfg.get("extreme_panic_open_pct", -7.0))
        w2s_ratio_threshold = float(auction_cfg.get("weak_to_strong_ratio_pct", 3.0))
        w2s_open_threshold = float(auction_cfg.get("weak_to_strong_open_pct", 1.5))

        # Check yesterday's strength (consecutive limit ups or close change)
        yest_board = int(data.get("consecutive_limit_ups") or data.get("board") or 0)
        yest_pct = float(data.get("prev_change_pct") or data.get("yesterday_change_pct") or 0.0)

        # A. Panic Dumping Detection (核按钮 / 强转弱)
        # If open_pct <= -7% (deep floor) OR (open_pct <= -4% after strong board/gain >= 5%)
        is_panic = (
            open_pct <= extreme_panic_threshold
            or (open_pct <= panic_threshold and (yest_board >= 1 or yest_pct >= 5.0))
        )

        if is_panic:
            reason = (
                f"🛑 TSP 集合竞价核按钮恐慌（低开 {open_pct:.2f}%，集中抛盘涌出），"
                f"严禁早盘接盘！"
            )
            return {
                "symbol": str(symbol_code),
                "signal": "panic_dumping",
                "open_pct": open_pct,
                "auction_ratio_pct": auction_ratio_pct,
                "is_weak_to_strong": False,
                "is_panic_dumping": True,
                "blocked_buy": True,
                "mss_delta": -15.0,
                "reason": reason,
            }

        # B. Weak to Strong Detection (爆量抢筹 / 弱转强)
        # If auction turnover ratio >= 3% and open_pct >= +1.5%
        is_w2s = (
            auction_ratio_pct >= w2s_ratio_threshold
            and open_pct >= w2s_open_threshold
        )

        if is_w2s:
            reason = (
                f"🟢 TSP 集合竞价爆量弱转强（竞价成交额占比 {auction_ratio_pct:.1f}% 爆量抢筹，"
                f"高开 +{open_pct:.2f}%），主力开盘抢筹确认！"
            )
            return {
                "symbol": str(symbol_code),
                "signal": "weak_to_strong",
                "open_pct": open_pct,
                "auction_ratio_pct": auction_ratio_pct,
                "is_weak_to_strong": True,
                "is_panic_dumping": False,
                "blocked_buy": False,
                "mss_delta": 8.0,
                "reason": reason,
            }

        return {
            "symbol": str(symbol_code),
            "signal": "normal",
            "open_pct": open_pct,
            "auction_ratio_pct": auction_ratio_pct,
            "is_weak_to_strong": False,
            "is_panic_dumping": False,
            "blocked_buy": False,
            "mss_delta": 0.0,
            "reason": "",
        }

    except Exception as exc:
        logger.debug(f"[TSP Call Auction] evaluate_call_auction_divergence error: {exc}")
        return default_result
