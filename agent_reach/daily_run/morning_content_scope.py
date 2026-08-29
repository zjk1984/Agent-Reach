# -*- coding: utf-8
"""Scoped morning card content — macro headlines, market brief, close recap, symbol logic."""

from __future__ import annotations

import re
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code

_BULLISH_KW = ("上涨", "利好", "突破", "回暖", "复苏", "增产", "中标", "回购", "增长", "提振")
_BEARISH_KW = ("下跌", "利空", "暴跌", "制裁", "调查", "减持", "亏损", "预警", "停产", "下滑")
_SECTOR_KW: tuple[tuple[str, str], ...] = (
    ("半导体", "半导体"),
    ("芯片", "半导体"),
    ("存储", "半导体"),
    ("DDR", "半导体"),
    ("光通信", "通信"),
    ("光学", "光学"),
    ("AI", "AI算力"),
    ("算力", "AI算力"),
    ("石油", "能源"),
    ("黄金", "贵金属"),
    ("银行", "金融"),
    ("新能源", "新能源"),
    ("汽车", "汽车"),
)


def _holding_sectors(portfolio: dict[str, Any]) -> dict[str, set[str]]:
    by_code: dict[str, set[str]] = {}
    for row in (portfolio.get("holdings") or []) + (portfolio.get("watchlist") or []):
        if not isinstance(row, dict):
            continue
        code = _normalize_code(str(row.get("code") or ""))
        if not code:
            continue
        sectors = by_code.setdefault(code, set())
        sector = str(row.get("sector") or "").strip()
        if sector:
            sectors.add(sector)
        name = str(row.get("name") or "").strip()
        if name:
            sectors.add(name[:4])
    return by_code


def _portfolio_sector_labels(portfolio: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for sectors in _holding_sectors(portfolio).values():
        labels.update(sectors)
    return labels


def infer_impact_label(title: str) -> str:
    text = str(title or "")
    if any(k in text for k in _BEARISH_KW):
        return "利空"
    if any(k in text for k in _BULLISH_KW):
        return "利好"
    return "中性"


def infer_affected_sectors(title: str, portfolio: dict[str, Any]) -> str:
    text = str(title or "")
    hit: set[str] = set()
    for row in (portfolio.get("holdings") or []):
        if not isinstance(row, dict):
            continue
        sector = str(row.get("sector") or "").strip()
        name = str(row.get("name") or "").strip()
        if sector and sector in text:
            hit.add(sector)
        if name and (name in text or name[:2] in text):
            hit.add(sector or name[:4])
    for kw, label in _SECTOR_KW:
        if kw in text:
            hit.add(label)
    if hit:
        return "、".join(sorted(hit)[:3])
    pf_sectors = _portfolio_sector_labels(portfolio)
    for sector in pf_sectors:
        if sector and len(sector) >= 2 and sector in text:
            hit.add(sector)
    if hit:
        return "、".join(sorted(hit)[:3])
    return "综合"


def _headline_relevance(title: str, portfolio: dict[str, Any]) -> int:
    text = str(title or "")
    if not text.strip():
        return 0
    score = 0
    for row in (portfolio.get("holdings") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        sector = str(row.get("sector") or "").strip()
        code = str(row.get("code") or "").strip()
        if name and name in text:
            score += 4
        elif name and len(name) >= 2 and name[:2] in text:
            score += 2
        if sector and sector in text:
            score += 3
        if code and code in text:
            score += 2
    for kw, _label in _SECTOR_KW:
        if kw in text and any(kw in str(s) or _label in str(s) for s in _portfolio_sector_labels(portfolio)):
            score += 2
        elif kw in text:
            score += 1
    return score


def _normalize_headline_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"title": item.strip(), "platform": "60s", "url": ""}
    if not isinstance(item, dict):
        return {"title": "", "platform": "", "url": ""}
    title = str(item.get("title") or item.get("topic") or "").strip()
    return {
        "title": title,
        "platform": str(item.get("platform") or item.get("source") or "要闻"),
        "url": str(item.get("url") or item.get("link") or "").strip(),
        "hot_value": item.get("hot_value"),
    }


def collect_macro_headline_candidates(
    *,
    macro_signals: Optional[dict[str, Any]],
    sources: Optional[dict[str, Any]],
    portfolio: dict[str, Any],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def _add(raw: Any) -> None:
        row = _normalize_headline_item(raw)
        title = row.get("title") or ""
        if not title or title in seen:
            return
        seen.add(title)
        score = _headline_relevance(title, portfolio)
        out.append(
            {
                **row,
                "score": score,
                "sectors": infer_affected_sectors(title, portfolio),
                "impact": infer_impact_label(title),
            }
        )

    signals = macro_signals or {}
    for bucket in ("hot_topics_matched", "hot_topics"):
        for item in signals.get(bucket) or []:
            _add(item)

    hot_src = (sources or {}).get("hot_news") or {}
    if isinstance(hot_src, dict):
        summary = str(hot_src.get("summary") or "").strip()
        if summary and "；" in summary:
            for part in summary.split("；"):
                _add(part.strip())
        elif summary:
            _add(summary)

    out.sort(key=lambda r: (-int(r.get("score") or 0), str(r.get("title") or "")))
    return out


def select_macro_headlines(
    *,
    macro_signals: Optional[dict[str, Any]],
    sources: Optional[dict[str, Any]],
    portfolio: dict[str, Any],
    limit: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = collect_macro_headline_candidates(
        macro_signals=macro_signals,
        sources=sources,
        portfolio=portfolio,
    )
    relevant = [row for row in candidates if int(row.get("score") or 0) > 0]
    featured = relevant[:limit]
    if len(featured) < limit:
        for row in candidates:
            if row in featured:
                continue
            featured.append(row)
            if len(featured) >= limit:
                break
    extra = [row for row in candidates if row not in featured][:8]
    return featured[:limit], extra


def render_macro_headlines_markdown(
    featured: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> str:
    if not featured and not extra:
        return ""
    lines = ["**宏观要闻**", ""]
    for idx, row in enumerate(featured, start=1):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        sectors = str(row.get("sectors") or "综合")
        impact = str(row.get("impact") or "中性")
        lines.append(
            f"{idx}. {title[:96]} · 影响板块：**{sectors}** · 对持仓影响：**{impact}**"
        )
    if extra:
        links: list[str] = []
        for row in extra[:5]:
            title = str(row.get("title") or "").strip()[:48]
            url = str(row.get("url") or "").strip()
            if url:
                links.append(f"[{title}]({url})")
            elif title:
                links.append(title)
        if links:
            lines.extend(["", f"**延伸阅读：** {' · '.join(links)}"])
    return "\n".join(lines).strip()


def render_domestic_market_brief(
    *,
    snapshot: Optional[dict[str, Any]],
    macro_signals: Optional[dict[str, Any]],
) -> str:
    snap = snapshot or {}
    sources = snap.get("sources") or {}
    signals = macro_signals or {}
    parts: list[str] = []

    idx_pct = signals.get("index_change_pct")
    if idx_pct is not None:
        parts.append(f"A股指数 **{float(idx_pct):+.2f}%**")
    else:
        quote = sources.get("quote") or {}
        if isinstance(quote, dict) and quote.get("summary"):
            parts.append(str(quote["summary"]))

    flow = signals.get("northbound_flow_yi")
    if flow is not None:
        parts.append(f"北向 **{float(flow):+.2f} 亿**")
    else:
        flow_src = sources.get("flow") or {}
        if isinstance(flow_src, dict) and flow_src.get("summary"):
            parts.append(str(flow_src["summary"]))

    if not parts:
        macro_summary = str(snap.get("macro_summary") or "").strip()
        if macro_summary:
            first = macro_summary.split("|")[0].split("；")[0].strip()
            if first:
                parts.append(first[:120])

    if not parts:
        return ""
    return "**大盘分析**\n\n" + " · ".join(parts[:2])


def build_prior_close_recap(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    from agent_reach.daily_run.daily_pnl_history import load_daily_pnl_history
    from agent_reach.daily_run.prior_close import load_close_baseline, prev_trading_day
    from agent_reach.daily_run.trade_calendar import today_shanghai

    lines: list[str] = []
    yday = prev_trading_day(today_shanghai())
    pnl_rows = load_daily_pnl_history(start=yday, end=yday, settings=settings)
    if pnl_rows:
        row = pnl_rows[-1]
        pct_s = f"（{float(row.daily_pnl_pct):+.2f}%）" if row.daily_pnl_pct is not None else ""
        lines.append(f"昨日组合盈亏 **{float(row.daily_pnl):+,.0f}**{pct_s}")

    verdicts: list[str] = []
    mss_vals: list[float] = []
    for holding in portfolio.get("holdings") or []:
        if not isinstance(holding, dict):
            continue
        code = _normalize_code(str(holding.get("code") or ""))
        if not code:
            continue
        baseline = load_close_baseline(code, target_day=yday, settings=settings)
        if not baseline:
            continue
        verdicts.append(str(baseline.get("verdict") or "观察"))
        if baseline.get("mss_final") is not None:
            mss_vals.append(float(baseline["mss_final"]))

    if verdicts:
        watch_n = sum(1 for v in verdicts if v == "观察")
        avoid_n = sum(1 for v in verdicts if v == "回避")
        if avoid_n >= max(1, len(verdicts) // 2):
            tone = f"昨日收盘以**回避**为主（{avoid_n}/{len(verdicts)} 只）"
        elif watch_n >= max(1, len(verdicts) // 2):
            tone = f"昨日收盘以**观察**为主（{watch_n}/{len(verdicts)} 只）"
        else:
            tone = f"昨日收盘结论：**可做** {len(verdicts) - watch_n - avoid_n} 只"
        if mss_vals:
            tone += f"，MSS 区间 **{min(mss_vals):.0f}~{max(mss_vals):.0f}**"
        lines.append(tone)

    return " · ".join(lines[:2])


def render_prior_close_recap_markdown(
    portfolio: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> str:
    recap = build_prior_close_recap(portfolio, settings=settings)
    if not recap:
        return ""
    return f"**昨日收盘要点**\n\n{recap}"


def render_symbol_morning_logic_markdown(
    report: dict[str, Any],
    snapshot: Optional[dict[str, Any]] = None,
) -> str:
    """Per-symbol card body: stock logic only (no macro / portfolio market analysis)."""
    lines: list[str] = [
        f"**结论：{report.get('verdict')}**（置信度：{report.get('confidence')}）",
        "",
        f"**MSS：** {report.get('mss_final')} 分",
        "",
        f"**个股逻辑：** {report.get('reasoning') or '—'}",
        "",
        f"**失效条件：** {report.get('invalidation') or '—'}",
    ]
    if report.get("entry_price") is not None:
        lines.append(f"**参考入场：** {float(report['entry_price']):.2f}")
    if report.get("stop_loss_price") is not None:
        lines.append(f"**止损参考：** {float(report['stop_loss_price']):.2f}")

    code = str(report.get("code") or (snapshot or {}).get("code") or "")
    if snapshot and code:
        from agent_reach.daily_run.symbol_news import render_symbol_news_markdown

        news_md = render_symbol_news_markdown(code, snapshot, name=str(report.get("name") or ""))
        if news_md:
            lines.extend(["", news_md])
    return "\n".join(lines).strip()


def render_merged_symbol_logic_markdown(entries: list[tuple]) -> str:
    if not entries:
        return ""
    if len(entries) == 1:
        name, _code, report = entries[0][0], entries[0][1], entries[0][2]
        snap = entries[0][3] if len(entries[0]) > 3 else None
        body = render_symbol_morning_logic_markdown(report, snapshot=snap)
        return f"### {name}\n\n{body}"

    lines = [f"**个股研判 · {len(entries)} 只**（大盘/宏观见持仓速览）", ""]
    for entry in entries:
        name, code, report = entry[0], entry[1], entry[2]
        snap = entry[3] if len(entry) > 3 else None
        lines.append(f"### {name} ({code})")
        logic = render_symbol_morning_logic_markdown(report, snapshot=snap)
        logic_lines = [ln for ln in logic.splitlines() if not ln.startswith("**结论：")]
        lines.extend(logic_lines)
        lines.append("")
    return "\n".join(lines).strip()


_MACRO_FOCUS_RE = re.compile(
    r"热股|热帖|热搜|宏观|北向|大盘|雪球|60s|要闻|板块主线|指数"
)


def render_scoped_morning_narrative_markdown(narrative: Optional[dict[str, Any]]) -> str:
    data = narrative or {}
    if data.get("skipped"):
        return ""
    lines = ["## 📋 规则解读（决策摘要）", ""]
    if data.get("summary"):
        lines.append(str(data["summary"]))
    focus = [
        str(item).strip()
        for item in (data.get("focus_points") or [])
        if str(item).strip() and not _MACRO_FOCUS_RE.search(str(item))
    ][:2]
    if focus:
        if data.get("summary"):
            lines.append("")
        lines.append("**关注点**")
        for item in focus:
            lines.append(f"- {item[:120]}")
    risks = [str(item).strip() for item in (data.get("risk_alerts") or []) if str(item).strip()][:2]
    if risks:
        lines.append("")
        lines.append("**风险**")
        for item in risks:
            lines.append(f"- {item[:120]}")
    return "\n".join(lines).strip()
