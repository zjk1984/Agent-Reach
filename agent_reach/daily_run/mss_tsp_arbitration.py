# -*- coding: utf-8 -*-
"""AR-2: Unified ruling when MSS macro signals conflict with TSP 退潮/主线 overlays."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.verdict import VerdictResult


def mss_tsp_arbitration_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = dict(((settings or {}).get("signal_arbitration") or {}).get("mss_tsp") or {})
    phases = raw.get("cap_verdict_on_regime_phases")
    if not isinstance(phases, list):
        phases = ["retreat", "freezing"]
    return {
        "enabled": raw.get("enabled", True) is not False,
        "cap_verdict_on_retreat": raw.get("cap_verdict_on_retreat", True) is not False,
        "cap_verdict_on_regime_phases": [str(p) for p in phases],
        "log_to_manifest": raw.get("log_to_manifest", True) is not False,
        "log_to_decision_trace": raw.get("log_to_decision_trace", True) is not False,
    }


def _tsp_quant_enabled(settings: dict[str, Any]) -> bool:
    tsp = dict(settings.get("tsp_quant") or {})
    return tsp.get("enabled", True) is not False


def probe_tsp_session_context(
    settings: dict[str, Any],
    *,
    job: str = "intraday",
    live_breadth: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Best-effort TSP session snapshot for arbitration (no network when breadth cached)."""
    out: dict[str, Any] = {
        "job": job,
        "phase": None,
        "phase_label": None,
        "intraday_retreat": False,
        "retreat_reason": "",
        "mainline_hint": None,
    }
    if not _tsp_quant_enabled(settings):
        out["disabled"] = True
        return out

    breadth = live_breadth
    if breadth is None and job in ("intraday", "midday"):
        try:
            from agent_reach.daily_run.tsp.config import tsp_quant_cfg
            from agent_reach.daily_run.tsp.intraday_sentinel import get_live_market_breadth_and_phase

            intraday_cfg = (tsp_quant_cfg(settings).get("intraday") or {})
            if intraday_cfg.get("enabled", True) is not False:
                breadth = get_live_market_breadth_and_phase(settings)
        except Exception:
            breadth = None

    if isinstance(breadth, dict):
        out["phase"] = breadth.get("phase")
        out["phase_label"] = breadth.get("phase_name") or breadth.get("description")

    if breadth is None and snapshot:
        em = (snapshot.get("macro_signals") or {}).get("emotion") or {}
        if em.get("limit_up") is not None or em.get("broken_rate") is not None:
            try:
                from agent_reach.daily_run.tsp.market_regime import compute_tsp_market_phase

                res = compute_tsp_market_phase(
                    limit_up_count=int(em.get("limit_up") or 0),
                    limit_down_count=int(em.get("limit_down") or 0),
                    broken_rate=float(em.get("broken_rate") or 0.0),
                    highest_board=int(em.get("highest_board") or 1),
                )
                out["phase"] = res.get("phase")
                out["phase_label"] = res.get("phase_label") or res.get("summary")
            except Exception:
                pass

    try:
        from agent_reach.daily_run.tsp.intraday_sentinel import check_intraday_retreat_risk

        is_retreat, reason = check_intraday_retreat_risk(settings, live_breadth=breadth)
        out["intraday_retreat"] = bool(is_retreat)
        out["retreat_reason"] = str(reason or "")
    except Exception:
        pass

    code = str((snapshot or {}).get("code") or "")
    if code and breadth:
        try:
            from agent_reach.daily_run.tsp.intraday_sentinel import match_symbol_tsp_mainline

            m = match_symbol_tsp_mainline(code, snapshot or {}, settings, live_breadth=breadth)
            if m.is_mainline:
                out["mainline_hint"] = {
                    "sector": m.sector_name,
                    "score": m.score,
                    "highest_board": m.highest_board,
                }
        except Exception:
            pass

    return out


def _mss_side(verdict: VerdictResult, settings: dict[str, Any]) -> str:
    labels = settings.get("verdict_labels", {})
    buy_label = labels.get("buy", "可做")
    avoid_label = labels.get("avoid", "回避")
    if verdict.label_key == "avoid" or verdict.verdict == avoid_label:
        return "avoid"
    if verdict.label_key == "buy" or verdict.verdict == buy_label:
        return "buy"
    return "watch"


def arbitrate_mss_tsp(
    evaluation: dict[str, Any],
    *,
    settings: dict[str, Any],
    job: str = "intraday",
    live_breadth: Optional[dict[str, Any]] = None,
    snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Align displayed verdict with TSP session risk when MSS says buy but TSP says no chase.

    Trade gates (evaluate_trade tsp_retreat, min_cash, fund gate) are unchanged.
    """
    cfg = mss_tsp_arbitration_cfg(settings)
    record: dict[str, Any] = {
        "enabled": cfg["enabled"],
        "job": job,
        "conflict": False,
        "winner": None,
        "rule_id": None,
        "mss_side": None,
        "tsp_side": None,
        "verdict_before": None,
        "verdict_after": None,
        "reason": "",
    }
    if not cfg["enabled"] or not _tsp_quant_enabled(settings):
        return record

    verdict = evaluation.get("verdict")
    report = evaluation.get("report") or {}
    snap = snapshot or report
    if not isinstance(verdict, VerdictResult):
        return record

    tsp_ctx = probe_tsp_session_context(settings, job=job, live_breadth=live_breadth, snapshot=snap)
    record["tsp_context"] = tsp_ctx

    mss_side = _mss_side(verdict, settings)
    record["mss_side"] = mss_side
    record["verdict_before"] = verdict.verdict

    phase = str(tsp_ctx.get("phase") or "")
    tsp_retreat = bool(tsp_ctx.get("intraday_retreat"))
    regime_retreat = phase in set(cfg["cap_verdict_on_regime_phases"])

    if tsp_retreat:
        tsp_side = "retreat_block_chase"
    elif regime_retreat:
        tsp_side = "regime_defensive"
    elif tsp_ctx.get("mainline_hint"):
        tsp_side = "mainline_supportive"
    else:
        tsp_side = "neutral"
    record["tsp_side"] = tsp_side

    labels = settings.get("verdict_labels", {})
    buy_label = labels.get("buy", "可做")
    watch_label = labels.get("watch", "观察")

    winner = "mss"
    rule_id = "harmonized"
    reason = "MSS 与 TSP 无展示层冲突"
    apply_cap = False

    if mss_side == "buy" and tsp_side == "retreat_block_chase" and cfg["cap_verdict_on_retreat"]:
        winner = "tsp"
        rule_id = "tsp_intraday_retreat_over_mss_buy"
        reason = tsp_ctx.get("retreat_reason") or "TSP 盘中退潮禁追高"
        apply_cap = True
        record["conflict"] = True
    elif mss_side == "buy" and tsp_side == "regime_defensive":
        winner = "tsp"
        rule_id = "tsp_regime_defensive_over_mss_buy"
        reason = (
            f"TSP 情绪周期「{tsp_ctx.get('phase_label') or phase}」"
            " — 展示 verdict 上限「观察」（买入仍以交易门禁为准）"
        )
        apply_cap = True
        record["conflict"] = True
    elif mss_side == "buy" and tsp_side == "mainline_supportive":
        winner = "mss"
        rule_id = "mss_verdict_tsp_mainline_trade_only"
        hint = tsp_ctx.get("mainline_hint") or {}
        reason = (
            f"MSS「可做」保持；TSP 主线【{hint.get('sector', '—')}】"
            "仅作用于交易层共振/门槛（不抬高展示标签）"
        )
        if hint:
            record["conflict"] = True
    elif mss_side == "avoid":
        winner = "mss"
        rule_id = "mss_macro_veto"
        reason = "MSS 宏观否决优先于 TSP 主线激励"

    record["winner"] = winner
    record["rule_id"] = rule_id
    record["reason"] = reason

    if apply_cap and verdict.label_key == "buy":
        downgrade = list(verdict.downgrade_reasons)
        downgrade.append(f"AR-2 MSS↔TSP：{reason}")
        new_verdict = VerdictResult(
            verdict=watch_label,
            confidence=verdict.confidence if verdict.confidence != "高" else "中",
            mss_final=verdict.mss_final,
            entry_price=verdict.entry_price,
            stop_loss_price=verdict.stop_loss_price,
            invalidation=verdict.invalidation,
            reasoning=verdict.reasoning,
            downgrade_reasons=downgrade,
            blocked=verdict.blocked,
            label_key="watch",
        )
        evaluation["verdict"] = new_verdict
        report["verdict"] = watch_label
        report["downgrade_reasons"] = downgrade
        report["mss_tsp_arbitration"] = record
        evaluation["report"] = report
        record["verdict_after"] = watch_label
    else:
        record["verdict_after"] = verdict.verdict
        report["mss_tsp_arbitration"] = record
        evaluation["report"] = report

    evaluation["mss_tsp_arbitration"] = record
    return record


def attach_mss_tsp_arbitration_to_manifest(payload: dict[str, Any]) -> None:
    """Promote per-symbol/session MSS↔TSP arbitration onto scheduled job manifest payload."""
    if not isinstance(payload, dict):
        return
    rows: list[dict[str, Any]] = []

    def _collect(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        rec = obj.get("mss_tsp_arbitration")
        if isinstance(rec, dict) and rec.get("enabled") is not False:
            rows.append(rec)
        ev = obj.get("evaluation")
        if isinstance(ev, dict):
            inner = ev.get("mss_tsp_arbitration")
            if isinstance(inner, dict):
                rows.append(inner)

    _collect(payload.get("result") or {})
    _collect(payload)
    for sym in payload.get("symbol_results") or []:
        if not isinstance(sym, dict):
            continue
        _collect(sym.get("result") or {})
        _collect((sym.get("result") or {}).get("evaluation") or {})

    trade = payload.get("trade_result") or (payload.get("result") or {}).get("trade_result")
    if isinstance(trade, dict):
        trace = trade.get("decision_trace")
        if isinstance(trace, dict):
            ctx = trace.get("context") or {}
            if isinstance(ctx.get("mss_tsp_arbitration"), dict):
                rows.append(ctx["mss_tsp_arbitration"])

    if not rows:
        return

    conflicts = [r for r in rows if r.get("conflict")]
    payload["mss_tsp_arbitration"] = {
        "count": len(rows),
        "conflicts": len(conflicts),
        "last": rows[-1],
        "samples": rows[-5:],
    }
    if conflicts:
        payload["mss_tsp_arbitration"]["last_conflict"] = conflicts[-1]