# -*- coding: utf-8
"""Investment thesis tracker — buy rationale, assumptions, red lines."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.berkshire.config import berkshire_enabled, thesis_dir, thesis_snapshot_dir
from agent_reach.daily_run.snapshot_builder import _normalize_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def thesis_path(code: str, settings: dict[str, Any] | None = None) -> Path:
    norm = _normalize_code(code)
    return thesis_dir(settings) / f"{norm}.json"


def load_thesis(code: str, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    path = thesis_path(code, settings)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_thesis(doc: dict[str, Any], settings: dict[str, Any] | None = None) -> Path:
    code = _normalize_code(str(doc.get("code", "")))
    if not code:
        raise ValueError("thesis missing code")
    root = thesis_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    doc["code"] = code
    doc["updated_at"] = _now_iso()
    path = root / f"{code}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _default_red_lines() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "text": "管理层诚信问题（财务造假、重大关联交易未披露）",
            "severity": "fatal",
            "action": "立即清仓",
        },
        {
            "id": 2,
            "text": "MSS 跌破 macro_veto 且 lookback 无 recovery",
            "severity": "severe",
            "action": "防御性减仓并重新评估",
        },
        {
            "id": 3,
            "text": "核心假设连续 2 次季度检查为受损/破裂",
            "severity": "severe",
            "action": "减仓 50% 并深度复盘",
        },
    ]


def build_thesis_from_snapshot(
    snapshot: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = _normalize_code(str(snapshot.get("code", "")))
    name = str(snapshot.get("name") or code)
    mss = snapshot.get("mss_final")
    verdict = snapshot.get("verdict") or "观察"
    price = snapshot.get("price")
    reasoning = str(snapshot.get("reasoning") or snapshot.get("macro_summary") or "")[:200]

    holding = None
    for h in (portfolio or {}).get("holdings") or []:
        if _normalize_code(str(h.get("code", ""))) == code:
            holding = h
            break

    core = (
        f"跟踪 {name}({code})：MSS {mss} · {verdict}。"
        f"{'持仓 ' + str(holding.get('shares')) + ' 股' if holding else '观察池/候选'}。"
        f"{reasoning[:120]}"
    ).strip()

    assumptions = [
        {
            "id": 1,
            "text": "MSS 维持 ≥ macro_veto，宏观因子未触发一票否决",
            "status": "green",
            "check": "mss_vs_veto",
        },
        {
            "id": 2,
            "text": "lookback MSS 未持续走弱（无 memory defensive 触发）",
            "status": "green",
            "check": "lookback_trend",
        },
        {
            "id": 3,
            "text": "无重大负面公告/舆情（watchlist intel 未命中红线）",
            "status": "green",
            "check": "intel",
        },
    ]

    return {
        "code": code,
        "name": name,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "core_thesis": core,
        "mirror_test": core[:200],
        "assumptions": assumptions,
        "red_lines": _default_red_lines(),
        "valuation_anchor": {
            "price": price,
            "mss": mss,
            "verdict": verdict,
            "as_of": snapshot.get("as_of"),
        },
        "history": [],
    }


def sync_thesis_from_snapshot(
    snapshot: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    portfolio: dict[str, Any] | None = None,
    phase: str = "close",
) -> dict[str, Any]:
    """Create or update thesis; append daily snapshot to history."""
    if not berkshire_enabled(settings, key="thesis_tracker"):
        return {"skipped": True, "reason": "berkshire.thesis_tracker disabled"}

    code = _normalize_code(str(snapshot.get("code", "")))
    if not code:
        return {"skipped": True, "reason": "missing code"}

    existing = load_thesis(code, settings)
    if existing is None:
        doc = build_thesis_from_snapshot(snapshot, settings=settings, portfolio=portfolio)
        action = "created"
    else:
        doc = dict(existing)
        doc["valuation_anchor"] = {
            "price": snapshot.get("price"),
            "mss": snapshot.get("mss_final"),
            "verdict": snapshot.get("verdict"),
            "as_of": snapshot.get("as_of"),
        }
        action = "updated"

    entry = {
        "date": snapshot.get("as_of") or _now_iso(),
        "phase": phase,
        "mss": snapshot.get("mss_final"),
        "verdict": snapshot.get("verdict"),
        "price": snapshot.get("price"),
    }
    history = list(doc.get("history") or [])
    if not history or history[-1].get("mss") != entry.get("mss"):
        history.append(entry)
    doc["history"] = history[-30:]

    path = save_thesis(doc, settings)
    _save_daily_snapshot(code, doc, settings)
    return {"applied": True, "action": action, "path": str(path), "code": code}


def _save_daily_snapshot(code: str, doc: dict[str, Any], settings: dict[str, Any] | None) -> None:
    from agent_reach.daily_run.trade_calendar import today_shanghai

    snap_dir = thesis_snapshot_dir(settings)
    snap_dir.mkdir(parents=True, exist_ok=True)
    day = today_shanghai().isoformat()
    path = snap_dir / f"{code}_{day}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def thesis_health_score(doc: dict[str, Any]) -> tuple[int, str]:
    """Simple health 1-10 from assumption statuses."""
    assumptions = doc.get("assumptions") or []
    score = 10
    for a in assumptions:
        st = str(a.get("status") or "green").lower()
        if st in ("black", "broken", "破裂"):
            score -= 3
        elif st in ("red", "受损", "damaged"):
            score -= 2
        elif st in ("yellow", "弱化", "weak"):
            score -= 1
    score = max(1, min(10, score))
    if score >= 8:
        label = "完整"
    elif score >= 6:
        label = "边际弱化"
    elif score >= 4:
        label = "受损"
    else:
        label = "破裂"
    return score, label


def render_thesis_markdown(doc: dict[str, Any]) -> str:
    score, label = thesis_health_score(doc)
    lines = [
        f"**投资论文** · {doc.get('name')} ({doc.get('code')})",
        f"- 健康度：**{score}/10**（{label}）",
        f"- 核心论文：{doc.get('core_thesis', '')[:300]}",
    ]
    anchor = doc.get("valuation_anchor") or {}
    if anchor:
        lines.append(
            f"- 估值锚点：MSS {anchor.get('mss')} · {anchor.get('verdict')} · 价 {anchor.get('price')}"
        )
    return "\n".join(lines)
