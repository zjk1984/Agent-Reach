# -*- coding: utf-8 -*-
"""TSP Mainline Sector Ranking & Quant Scoring.

Adapted from TSP's mainline quant scoring formula:
Score = 0.35 * count_score + 0.25 * height_score + 0.25 * cap_score + 0.15 * width_score

Directly quantifies the trading heuristic:
"同板块涨停越多、身位板越高、板块市值越中等均衡、二板梯队越完整，越是主升主线".
"""

from __future__ import annotations

from typing import Any, Optional


def score_mainline_sector(
    *,
    name: str,
    limit_up_count: int,
    highest_board: int = 1,
    two_board_count: int = 0,
    market_cap_median_yi: float = 0.0,
    max_count: int = 15,
    max_height: int = 7,
) -> float:
    """Calculate single sector mainline strength score normalized to 0-100."""
    # Count component: 35%
    c_norm = min(1.0, limit_up_count / max(1, max_count))
    score_count = c_norm * 35.0

    # Height component: 25% (highest board in sector)
    h_norm = min(1.0, highest_board / max(1, max_height))
    score_height = h_norm * 25.0

    # Width component: 15% (two board continuity)
    w_norm = min(1.0, two_board_count / 3.0)
    score_width = w_norm * 15.0

    # Capital median component: 25% (sweet spot 50-300亿)
    if 50.0 <= market_cap_median_yi <= 300.0:
        c_cap = 1.0
    elif market_cap_median_yi < 50.0:
        c_cap = max(0.2, market_cap_median_yi / 50.0)
    else:
        # > 300亿: penalty for slow mega-caps
        c_cap = max(0.3, 1.0 - (market_cap_median_yi - 300.0) / 1000.0)
    score_cap = c_cap * 25.0

    total_score = score_count + score_height + score_width + score_cap
    return round(total_score, 1)


def rank_tsp_mainlines(
    limit_up_stocks_or_groups: Any,
    *,
    min_limit_ups: int = 2,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Group limit-up stocks or use pre-grouped sectors and rank by mainline strength score."""
    if not limit_up_stocks_or_groups:
        return []

    if isinstance(limit_up_stocks_or_groups, dict):
        groups = {
            k: list(v) for k, v in limit_up_stocks_or_groups.items()
            if str(k).strip() and str(k).strip() != "其他"
        }
    else:
        groups = {}
        for s in limit_up_stocks_or_groups:
            sec = str(s.get("industry") or s.get("sector") or "其他").strip() or "其他"
            if sec == "其他":
                continue
            groups.setdefault(sec, []).append(s)

    if not groups:
        return []

    max_count = max(len(v) for v in groups.values())

    results: list[dict[str, Any]] = []
    for name, stocks in groups.items():
        if len(stocks) < min_limit_ups:
            continue

        # Inspect ladder & caps
        highest_board = 1
        two_board_count = 0
        caps: list[float] = []

        for stock in stocks:
            pct = float(stock.get("change_pct") or 0)
            board = stock.get("consecutive_limit_ups")
            if board is None:
                board = max(1, int(round(pct / 10))) if pct > 15 else 1
            highest_board = max(highest_board, int(board))
            if int(board) == 2:
                two_board_count += 1

            cap_raw = stock.get("market_capital")
            if cap_raw:
                try:
                    caps.append(float(cap_raw) / 1e8)
                except (TypeError, ValueError):
                    pass

        median_cap = sorted(caps)[len(caps) // 2] if caps else 100.0

        score = score_mainline_sector(
            name=name,
            limit_up_count=len(stocks),
            highest_board=highest_board,
            two_board_count=two_board_count,
            market_cap_median_yi=median_cap,
            max_count=max_count,
        )

        top_stocks = [
            {
                "code": s.get("code"),
                "name": s.get("name"),
                "change_pct": s.get("change_pct"),
            }
            for s in stocks[:3]
        ]

        results.append(
            {
                "sector": name,
                "score": score,
                "limit_up_count": len(stocks),
                "highest_board": highest_board,
                "two_board_count": two_board_count,
                "top_stocks": top_stocks,
            }
        )

    results.sort(key=lambda x: float(x["score"]), reverse=True)
    return results[:limit]
