# -*- coding: utf-8
"""Akshare limit-up/down/broken pools when Eastmoney clist is unavailable."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.akshare_adapter import AKShareError, _import_akshare


def _pool_date(review_date: str) -> str:
    return review_date.replace("-", "")


def _row_limit_up_stock(row: Any) -> dict[str, Any]:
    code = str(row.get("代码", "")).zfill(6)
    try:
        change_pct = float(row.get("涨跌幅") or 0)
    except (TypeError, ValueError):
        change_pct = 10.0
    industry = str(row.get("所属行业") or "").strip()
    boards_raw = row.get("连板数")
    consecutive = None
    if boards_raw is not None and str(boards_raw).strip() != "":
        try:
            consecutive = max(1, int(float(boards_raw)))
        except (TypeError, ValueError):
            consecutive = None
    out = {
        "code": code,
        "name": str(row.get("名称", code)).strip(),
        "change_pct": change_pct,
        "industry": industry or "其他",
        "source": "akshare_zt_pool",
    }
    if consecutive is not None:
        out["consecutive_limit_ups"] = consecutive
    return out


def fetch_akshare_limit_pools(
    review_date: str,
    *,
    include_stocks: bool = True,
) -> dict[str, Any]:
    """Fetch limit-up/down/broken pools for a trading day (YYYYMMDD)."""
    ak = _import_akshare()
    day = _pool_date(review_date)

    zt_df = ak.stock_zt_pool_em(date=day)
    dt_df = ak.stock_zt_pool_dtgc_em(date=day)
    zb_df = ak.stock_zt_pool_zbgc_em(date=day)

    limit_up = int(len(zt_df))
    limit_down = int(len(dt_df))
    broken_count = int(len(zb_df))
    broken_rate = (
        broken_count / (limit_up + broken_count) if (limit_up + broken_count) > 0 else 0.0
    )

    limit_up_stocks: list[dict[str, Any]] = []
    if include_stocks and limit_up > 0:
        for _, row in zt_df.iterrows():
            limit_up_stocks.append(_row_limit_up_stock(row))

    if limit_up == 0 and limit_down == 0 and broken_count == 0:
        summary = _fetch_legu_limit_summary()
        if summary:
            stat_day = str(summary.get("stat_date_yyyymmdd") or day)
            try:
                zt_df = ak.stock_zt_pool_em(date=stat_day)
                dt_df = ak.stock_zt_pool_dtgc_em(date=stat_day)
                zb_df = ak.stock_zt_pool_zbgc_em(date=stat_day)
                pool_up = int(len(zt_df))
                pool_down = int(len(dt_df))
                pool_broken = int(len(zb_df))
                if pool_up + pool_down + pool_broken > 0:
                    limit_up = pool_up or int(summary.get("limit_up") or 0)
                    limit_down = pool_down or int(summary.get("limit_down") or 0)
                    broken_count = pool_broken
                    broken_rate = (
                        broken_count / (limit_up + broken_count)
                        if (limit_up + broken_count) > 0
                        else 0.0
                    )
                    if include_stocks and pool_up > 0:
                        for _, row in zt_df.iterrows():
                            limit_up_stocks.append(_row_limit_up_stock(row))
                    return {
                        "limit_up": limit_up,
                        "limit_down": limit_down,
                        "broken_count": broken_count,
                        "broken_rate": round(broken_rate, 4),
                        "limit_up_stocks": limit_up_stocks,
                        "up_count": int(summary.get("up_count") or 0),
                        "down_count": int(summary.get("down_count") or 0),
                        "flat_count": int(summary.get("flat_count") or 0),
                        "source": "akshare_legu+pool",
                        "legu": summary,
                        "pool_date": stat_day,
                    }
            except Exception:
                pass

            limit_up = int(summary.get("limit_up") or 0)
            limit_down = int(summary.get("limit_down") or 0)
            return {
                "limit_up": limit_up,
                "limit_down": limit_down,
                "broken_count": 0,
                "broken_rate": 0.0,
                "limit_up_stocks": [],
                "up_count": int(summary.get("up_count") or 0),
                "down_count": int(summary.get("down_count") or 0),
                "flat_count": int(summary.get("flat_count") or 0),
                "source": "akshare_legu",
                "legu": summary,
            }
        raise AKShareError(f"akshare 涨跌停股池为空：{day}")

    return {
        "limit_up": limit_up,
        "limit_down": limit_down,
        "broken_count": broken_count,
        "broken_rate": round(broken_rate, 4),
        "limit_up_stocks": limit_up_stocks,
        "source": "akshare_limit_pools",
        "pool_date": day,
    }


def _fetch_legu_limit_summary() -> Optional[dict[str, Any]]:
    """Aggregate limit counts from stock_market_activity_legu (counts only)."""
    try:
        ak = _import_akshare()
        df = ak.stock_market_activity_legu()
    except Exception:
        return None
    if df is None or df.empty:
        return None
    items = dict(zip(df["item"].astype(str), df["value"]))
    limit_up = _optional_int(items.get("涨停"))
    limit_down = _optional_int(items.get("跌停"))
    if limit_up is None and limit_down is None:
        return None
    stat_raw = str(items.get("统计日期") or "")
    stat_yyyymmdd = ""
    if stat_raw:
        stat_yyyymmdd = stat_raw.replace("-", "").split(" ")[0][:8]

    return {
        "limit_up": limit_up or 0,
        "limit_down": limit_down or 0,
        "up_count": _optional_int(items.get("上涨")) or 0,
        "down_count": _optional_int(items.get("下跌")) or 0,
        "flat_count": _optional_int(items.get("平盘")) or 0,
        "real_limit_up": _optional_int(items.get("真实涨停")),
        "real_limit_down": _optional_int(items.get("真实跌停")),
        "stat_date": stat_raw,
        "stat_date_yyyymmdd": stat_yyyymmdd,
    }


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
