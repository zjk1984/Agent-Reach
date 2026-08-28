# -*- coding: utf-8
"""Per-symbol news snippets for daily-run Feishu cards (not portfolio macro/hot)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.xueqiu_hot_display import normalize_xueqiu_symbol


def _norm(code: str) -> str:
    return normalize_xueqiu_symbol(str(code or ""))


def _symbol_name(snapshot: dict[str, Any], code: str) -> str:
    norm = _norm(code)
    if str(snapshot.get("code") or "") == norm and snapshot.get("name"):
        return str(snapshot["name"])
    pf = snapshot.get("portfolio") or {}
    for row in (pf.get("holdings") or []) + (pf.get("watchlist") or []):
        if isinstance(row, dict) and _norm(str(row.get("code") or "")) == norm:
            return str(row.get("name") or norm)
    return norm


def _filter_hot_stocks(macro_signals: Optional[dict[str, Any]], code: str) -> list[dict[str, Any]]:
    norm = _norm(code)
    rows = (macro_signals or {}).get("portfolio_hot_stocks") or []
    return [row for row in rows if isinstance(row, dict) and _norm(str(row.get("code") or "")) == norm]


def _filter_hot_posts(
    macro_signals: Optional[dict[str, Any]],
    code: str,
    *,
    name: str = "",
) -> list[dict[str, Any]]:
    norm = _norm(code)
    name = (name or "").strip()
    rows = (macro_signals or {}).get("portfolio_hot_posts") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kws = [str(k).strip() for k in (row.get("matched_keywords") or []) if str(k).strip()]
        if name and name in kws:
            out.append(row)
            continue
        if norm and norm in str(row.get("title") or "") + str(row.get("text") or ""):
            out.append(row)
            continue
        if name and name in str(row.get("title") or "") + str(row.get("text") or ""):
            out.append(row)
    return out


def _symbol_sentiment_row(
    macro_signals: Optional[dict[str, Any]],
    code: str,
) -> Optional[dict[str, Any]]:
    norm = _norm(code)
    for row in (macro_signals or {}).get("portfolio_symbol_sentiment") or []:
        if isinstance(row, dict) and _norm(str(row.get("code") or "")) == norm:
            return row
    return None


def _filter_stock_search(
    macro_signals: Optional[dict[str, Any]],
    code: str,
) -> list[dict[str, Any]]:
    norm = _norm(code)
    return [
        row
        for row in (macro_signals or {}).get("xueqiu_stock_search") or []
        if isinstance(row, dict) and _norm(str(row.get("code") or "")) == norm
    ]


def _filter_exa_research(
    macro_signals: Optional[dict[str, Any]],
    code: str,
    *,
    name: str = "",
) -> list[dict[str, Any]]:
    norm = _norm(code)
    name = (name or "").strip()
    out: list[dict[str, Any]] = []
    for row in (macro_signals or {}).get("xueqiu_exa_research") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        if norm in label or (name and name in label):
            out.append(row)
    return out


def _intel_for_code(snapshot: dict[str, Any], code: str) -> Optional[dict[str, Any]]:
    intel = (snapshot.get("watchlist_intel") or {}).get(_norm(code))
    return intel if isinstance(intel, dict) else None


def symbol_stock_search_summary(
    code: str,
    macro_signals: Optional[dict[str, Any]],
    *,
    limit: int = 2,
) -> str:
    rows = _filter_stock_search(macro_signals, code)[:limit]
    if not rows:
        return ""
    parts = [
        f"{row.get('name') or _norm(code)}←{row.get('query') or ''}"
        for row in rows
        if isinstance(row, dict)
    ]
    return "搜索：" + " · ".join(parts) if parts else ""


def symbol_news_summary(
    code: str,
    snapshot: dict[str, Any],
    *,
    name: Optional[str] = None,
    limit: int = 2,
) -> str:
    """One-line summary for narrative focus points."""
    from agent_reach.daily_run.watchlist_intel import intel_reason_suffix

    norm = _norm(code)
    if not norm:
        return ""
    display = name or _symbol_name(snapshot, norm)
    macro_signals = snapshot.get("macro_signals") or {}
    parts: list[str] = []

    intel = _intel_for_code(snapshot, norm)
    if intel:
        hint = intel_reason_suffix(intel).lstrip(" · ")
        if hint:
            parts.append(hint[:80])

    for match in _filter_hot_stocks(macro_signals, norm)[:1]:
        board = str(match.get("board") or "热股")
        rank = match.get("rank")
        rank_s = f"#{rank}" if rank is not None else ""
        parts.append(f"热股榜 {board}{rank_s}")

    for post in _filter_hot_posts(macro_signals, norm, name=display)[:1]:
        title = str(post.get("title") or (post.get("text") or "")[:24]).strip() or "热帖"
        parts.append(title[:48])

    sentiment = _symbol_sentiment_row(macro_signals, norm)
    if sentiment:
        posts = sentiment.get("posts") or []
        if posts:
            top = posts[0]
            title = str(top.get("title") or (top.get("text") or "")[:20]).strip()
            if title:
                parts.append(f"讨论：{title[:40]}")

    for row in _filter_exa_research(macro_signals, norm, name=display)[:1]:
        summary = str(row.get("summary") or "").strip().splitlines()[0][:60]
        if summary:
            parts.append(f"调研 {summary}")

    if not parts:
        return ""
    return f"{display}：" + " · ".join(parts[:limit])


def render_symbol_news_markdown(
    code: str,
    snapshot: dict[str, Any],
    *,
    name: Optional[str] = None,
    post_limit: int = 2,
    news_limit: int = 2,
) -> str:
    """Markdown block with news directly related to one symbol."""
    from agent_reach.daily_run.watchlist_intel import _item_title

    norm = _norm(code)
    if not norm:
        return ""
    display = name or _symbol_name(snapshot, norm)
    macro_signals = snapshot.get("macro_signals") or {}
    lines: list[str] = []
    body_lines: list[str] = []

    intel = _intel_for_code(snapshot, norm)
    if intel:
        for key, label in (("announcements", "公告"), ("news", "资讯")):
            for item in (intel.get(key) or [])[:news_limit]:
                if not isinstance(item, dict):
                    continue
                title = _item_title(item)
                if title:
                    body_lines.append(f"- **{label}：** {title[:80]}")

    for match in _filter_hot_stocks(macro_signals, norm):
        board = str(match.get("board") or "热股")
        rank = match.get("rank")
        rank_s = f" #{rank}" if rank is not None else ""
        pct = match.get("percent")
        pct_s = f" · {float(pct):+.2f}%" if pct is not None else ""
        body_lines.append(f"- **热股榜：** {board}{rank_s}{pct_s}")

    for post in _filter_hot_posts(macro_signals, norm, name=display)[:post_limit]:
        title = str(post.get("title") or (post.get("text") or "")[:48]).strip() or "—"
        author = str(post.get("author") or "—").strip()
        url = str(post.get("url") or "").strip()
        row = f"- **热帖：** {title}（{author}）"
        if url:
            row += f"\n  {url}"
        body_lines.append(row)

    sentiment = _symbol_sentiment_row(macro_signals, norm)
    if sentiment:
        for post in (sentiment.get("posts") or [])[:post_limit]:
            title = str(post.get("title") or (post.get("text") or "")[:48]).strip() or "—"
            author = str(post.get("author") or "—").strip()
            body_lines.append(f"- **雪球讨论：** {title}（{author}）")

    for row in _filter_exa_research(macro_signals, norm, name=display)[:1]:
        summary = str(row.get("summary") or "").strip()
        if summary:
            body_lines.append(f"- **调研：** {summary[:240]}")

    for row in _filter_stock_search(macro_signals, norm)[:1]:
        query = str(row.get("query") or "").strip()
        title = str(row.get("title") or "").strip()
        if query or title:
            body_lines.append(f"- **搜索：** 「{query}」{title[:60]}")

    if not body_lines:
        return ""

    lines.append(f"**📰 {display} 相关资讯**")
    lines.append("")
    lines.extend(body_lines[: post_limit + news_limit + 4])
    return "\n".join(lines).strip()
