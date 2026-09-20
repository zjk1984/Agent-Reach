# -*- coding: utf-8
"""Cross-source sentiment alignment (OpenStock Adanos pattern, daily-run sources)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code


def get_source_alignment(bullish_values: list[float]) -> str:
    """Map spread of source bullish scores to alignment label."""
    if not bullish_values:
        return "无跨源舆情"
    if len(bullish_values) == 1:
        return "单源视图"

    min_v = min(bullish_values)
    max_v = max(bullish_values)
    spread = max_v - min_v
    avg = sum(bullish_values) / len(bullish_values)

    if spread <= 12 and avg >= 60:
        return "偏多对齐"
    if spread <= 12 and avg <= 40:
        return "偏空对齐"
    if spread <= 12:
        return "紧密对齐"
    if spread >= 25:
        return "显著分歧"
    return "混合"


def _clamp_bullish(score: float) -> float:
    return max(0.0, min(100.0, float(score)))


def _xueqiu_bullish(code: str, macro_signals: dict[str, Any]) -> Optional[float]:
    norm = _normalize_code(code)
    for row in macro_signals.get("portfolio_symbol_sentiment") or []:
        if _normalize_code(str(row.get("code") or "")) != norm:
            continue
        posts = row.get("posts") or []
        if not posts:
            return 55.0
        text = " ".join(
            str(p.get("title") or p.get("text") or "") for p in posts[:3] if isinstance(p, dict)
        )
        from agent_reach.daily_run.redfox_collector import BULLISH_WORDS, BEARISH_WORDS

        bull = sum(1 for w in BULLISH_WORDS if w in text)
        bear = sum(1 for w in BEARISH_WORDS if w in text)
        if bull == bear == 0:
            return 50.0
        return _clamp_bullish(50 + (bull - bear) * 8)

    for stock in macro_signals.get("portfolio_hot_stocks") or []:
        if _normalize_code(str(stock.get("code") or "")) != norm:
            continue
        chg = stock.get("change_pct")
        if chg is not None:
            return _clamp_bullish(50 + float(chg) * 3)
        return 55.0
    return None


def _redfox_bullish(code: str, redfox: dict[str, Any]) -> Optional[float]:
    norm = _normalize_code(code)
    titles: list[str] = []
    for item in redfox.get("matched") or []:
        if _normalize_code(str(item.get("code") or "")) == norm or norm in str(item.get("title") or ""):
            titles.append(str(item.get("title") or ""))
    if not titles:
        for item in (redfox.get("stock_feed_items") or [])[:20]:
            title = str(item.get("title") or "")
            if norm in title or str(item.get("code") or "") == norm:
                titles.append(title)
    if not titles:
        return None
    from agent_reach.daily_run.redfox_collector import _sentiment_score

    score = _sentiment_score(titles)
    return _clamp_bullish(50 + score * 10)


def _mss_bullish(snapshot: dict[str, Any]) -> Optional[float]:
    mss = snapshot.get("mss_final")
    if mss is None:
        breakdown = snapshot.get("mss_breakdown") or {}
        if breakdown:
            from agent_reach.daily_run.verdict import compute_mss

            mss = compute_mss(breakdown, {})
    if mss is None:
        return None
    return _clamp_bullish(float(mss))


def _market_emotion_bullish(market_review: Optional[dict[str, Any]]) -> Optional[float]:
    if not market_review:
        return None
    rating = str((market_review.get("emotion") or {}).get("rating") or "")
    mapping = {"强": 72.0, "中": 50.0, "弱": 28.0}
    for key, val in mapping.items():
        if key in rating:
            return val
    return 50.0


def build_symbol_sentiment_alignment(
    code: str,
    *,
    snapshot: Optional[dict[str, Any]] = None,
    macro_signals: Optional[dict[str, Any]] = None,
    redfox: Optional[dict[str, Any]] = None,
    market_review: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Aggregate daily-run sources into alignment summary for one symbol."""
    norm = _normalize_code(code)
    snap = snapshot or {}
    signals = macro_signals or snap.get("macro_signals") or {}
    rf = redfox or snap.get("redfox") or signals.get("redfox") or {}

    sources: list[dict[str, Any]] = []
    bullish_values: list[float] = []

    xq = _xueqiu_bullish(norm, signals)
    if xq is not None:
        sources.append({"source": "xueqiu", "label": "雪球", "bullish_pct": round(xq, 1)})
        bullish_values.append(xq)

    rf_score = _redfox_bullish(norm, rf if isinstance(rf, dict) else {})
    if rf_score is not None:
        sources.append({"source": "redfox", "label": "RedFox", "bullish_pct": round(rf_score, 1)})
        bullish_values.append(rf_score)

    mss = _mss_bullish(snap)
    if mss is not None:
        sources.append({"source": "mss", "label": "MSS", "bullish_pct": round(mss, 1)})
        bullish_values.append(mss)

    emo = _market_emotion_bullish(market_review)
    if emo is not None:
        sources.append({"source": "market_emotion", "label": "市场情绪", "bullish_pct": round(emo, 1)})
        bullish_values.append(emo)

    alignment = get_source_alignment(bullish_values)
    avg = round(sum(bullish_values) / len(bullish_values), 1) if bullish_values else None

    return {
        "code": norm,
        "name": snap.get("name") or code,
        "alignment": alignment,
        "bullish_average": avg,
        "available_sources": len(sources),
        "sources": sources,
    }


def build_portfolio_sentiment_alignment(
    *,
    symbol_rows: list[dict[str, Any]],
    primary_snapshot: Optional[dict[str, Any]] = None,
    market_review: Optional[dict[str, Any]] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    primary = primary_snapshot or {}
    macro = primary.get("macro_signals") or {}
    redfox = primary.get("redfox") or macro.get("redfox")
    out: list[dict[str, Any]] = []
    for row in symbol_rows[:limit]:
        code = _normalize_code(str(row.get("code") or ""))
        if not code:
            continue
        snap = row.get("snapshot") or row
        item = build_symbol_sentiment_alignment(
            code,
            snapshot={**primary, **snap, "code": code, "name": row.get("name") or snap.get("name")},
            macro_signals=macro,
            redfox=redfox if isinstance(redfox, dict) else None,
            market_review=market_review,
        )
        if item.get("available_sources", 0) >= 2:
            out.append(item)
    return out


def render_sentiment_alignment_markdown(
    items: list[dict[str, Any]],
) -> str:
    if not items:
        return ""
    lines = ["**跨源舆情对齐**", ""]
    for item in items[:6]:
        name = item.get("name") or item.get("code")
        code = item.get("code")
        alignment = item.get("alignment") or "—"
        avg = item.get("bullish_average")
        src_bits = []
        for s in item.get("sources") or []:
            src_bits.append(f"{s.get('label')} {s.get('bullish_pct')}%")
        avg_s = f"均 {avg}%" if avg is not None else ""
        lines.append(
            f"- **{name}** ({code}) · **{alignment}** {avg_s}"
            + (f" — {' · '.join(src_bits[:3])}" if src_bits else "")
        )
    return "\n".join(lines)
