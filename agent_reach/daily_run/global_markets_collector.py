# -*- coding: utf-8
"""Live overseas index quotes for morning cards — no stale fallback."""

from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

_EASTMONEY_UA = "Mozilla/5.0 (compatible; AgentReach/1.0)"
_EASTMONEY_REFERER = "https://quote.eastmoney.com/"
_SINA_REFERER = "https://finance.sina.com.cn"

KEY_GLOBAL_INDICES: tuple[tuple[str, str, str], ...] = (
    ("nasdaq", "100.NDX", "纳指"),
    ("sp500", "100.SPX", "标普500"),
    ("dow", "100.DJIA", "道指"),
)

HSI_FUTURES_SINA_CODE = "hf_HSI"
HSI_FUTURES_LABEL = "恒生期货"


def _shanghai_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _as_of_label(when: Optional[datetime] = None) -> str:
    dt = when or _shanghai_now()
    return f"截至 {dt.strftime('%H:%M')}"


def _parse_eastmoney_index(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw_price = data.get("f43")
    if raw_price is None:
        return None
    price = round(float(raw_price) / 100.0, 2)
    prev_raw = data.get("f60")
    prev_close = round(float(prev_raw) / 100.0, 2) if prev_raw is not None else None
    change_pct: Optional[float] = None
    raw_pct = data.get("f170")
    if raw_pct is not None:
        change_pct = round(float(raw_pct) / 100.0, 2)
    elif prev_close and prev_close > 0:
        change_pct = round((price - prev_close) / prev_close * 100.0, 2)
    return {
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "name": str(data.get("f58") or "").strip(),
    }


def _fetch_eastmoney_index(secid: str) -> Optional[dict[str, Any]]:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f43,f58,f60,f169,f170"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _EASTMONEY_UA, "Referer": _EASTMONEY_REFERER},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data") or {}
    return _parse_eastmoney_index(data)


def _parse_sina_hf_line(raw: str) -> Optional[dict[str, Any]]:
    if not raw or '=""' in raw:
        return None
    try:
        body = raw.split('"', 1)[1].rsplit('"', 1)[0]
    except IndexError:
        return None
    fields = body.split(",")
    if len(fields) < 8:
        return None
    try:
        price = round(float(fields[0]), 2)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    prev_close: Optional[float] = None
    try:
        prev_raw = fields[7]
        if prev_raw:
            prev_close = round(float(prev_raw), 2)
    except (TypeError, ValueError, IndexError):
        prev_close = None
    change_pct: Optional[float] = None
    if prev_close and prev_close > 0:
        change_pct = round((price - prev_close) / prev_close * 100.0, 2)
    quote_time = fields[6].strip() if len(fields) > 6 else ""
    return {
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "quote_time": quote_time,
        "name": HSI_FUTURES_LABEL,
    }


def _fetch_sina_hf(code: str) -> Optional[dict[str, Any]]:
    url = f"https://hq.sinajs.cn/list={code}"
    req = urllib.request.Request(url, headers={"Referer": _SINA_REFERER})
    with urllib.request.urlopen(req, timeout=12) as resp:
        text = resp.read().decode("gbk", "replace")
    prefix = f"var hq_str_{code}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return _parse_sina_hf_line(line)
    return None


def _failed_index(key: str, label: str, *, error: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ok": False,
        "error": error or "fetch_failed",
        "display_price": "⚠️ 数据获取失败",
        "display_change": "—",
    }


def _ok_index(key: str, label: str, quote: dict[str, Any]) -> dict[str, Any]:
    price = quote.get("price")
    prev = quote.get("prev_close")
    change = quote.get("change_pct")
    change_s = f"{float(change):+.2f}%" if change is not None else "—"
    prev_s = f"（昨收 {float(prev):,.2f}）" if prev is not None else ""
    return {
        "key": key,
        "label": label,
        "ok": True,
        "price": price,
        "prev_close": prev,
        "change_pct": change,
        "quote_time": quote.get("quote_time"),
        "display_price": f"{float(price):,.2f}" if price is not None else "—",
        "display_change": f"{change_s}{prev_s}",
    }


def fetch_key_global_markets(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Fetch mandatory overseas indices live; never reuse portfolio overrides."""
    when = now or _shanghai_now()
    indices: list[dict[str, Any]] = []

    for key, secid, label in KEY_GLOBAL_INDICES:
        try:
            quote = _fetch_eastmoney_index(secid)
        except Exception as exc:
            indices.append(_failed_index(key, label, error=str(exc)[:80]))
            continue
        if not quote or quote.get("price") is None:
            indices.append(_failed_index(key, label))
        else:
            indices.append(_ok_index(key, label, quote))

    try:
        hsi_quote = _fetch_sina_hf(HSI_FUTURES_SINA_CODE)
    except Exception as exc:
        hsi_quote = None
        hsi_error = str(exc)[:80]
    else:
        hsi_error = ""
    if hsi_quote:
        indices.append(_ok_index("hsi_futures", HSI_FUTURES_LABEL, hsi_quote))
    else:
        indices.append(_failed_index("hsi_futures", HSI_FUTURES_LABEL, error=hsi_error))

    ok_count = sum(1 for row in indices if row.get("ok"))
    return {
        "as_of": when.isoformat(),
        "as_of_label": _as_of_label(when),
        "indices": indices,
        "all_ok": ok_count == len(indices),
        "ok_count": ok_count,
        "required_count": len(indices),
    }


def render_global_markets_markdown(payload: Optional[dict[str, Any]]) -> str:
    """Markdown table for overseas indices section."""
    data = payload or {}
    indices = list(data.get("indices") or [])
    if not indices:
        return f"**外盘** · {data.get('as_of_label') or _as_of_label()}\n\n⚠️ 数据获取失败"

    lines = [
        f"**外盘** · {data.get('as_of_label') or _as_of_label()}",
        "",
        "| 指数 | 最新 | 较昨收 |",
        "|------|------|--------|",
    ]
    for row in indices:
        label = row.get("label") or row.get("key") or "—"
        price_s = row.get("display_price") or "⚠️ 数据获取失败"
        change_s = row.get("display_change") or "—"
        if not row.get("ok"):
            change_s = "⚠️ 数据获取失败"
        lines.append(f"| {label} | {price_s} | {change_s} |")
    if int(data.get("ok_count") or 0) < int(data.get("required_count") or len(indices)):
        lines.extend(["", "⚠️ 部分外盘指数获取失败，未使用历史缓存数据。"])
    return "\n".join(lines)
