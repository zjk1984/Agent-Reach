# -*- coding: utf-8
"""Lightweight 12:30 midday refresh for afternoon intraday (macro + Lookback anchor)."""

from __future__ import annotations

from typing import Any, Optional

from agent_reach.daily_run.pipeline import evaluate_snapshot
from agent_reach.daily_run.settings import effective_settings, load_settings


def midday_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = effective_settings(settings or load_settings())
    raw = cfg.get("midday") or {}
    report = cfg.get("report") or {}
    card_layout = str(report.get("midday_card_layout", "cards")).lower() not in (
        "legacy",
        "old",
        "false",
        "0",
    )
    macro_default = not card_layout
    if "macro_refresh" in raw:
        macro_refresh = raw.get("macro_refresh") is not False
    else:
        macro_refresh = macro_default
    return {
        "enabled": raw.get("enabled", True) is not False,
        "card_layout": card_layout,
        "macro_refresh": macro_refresh,
        "mss_experts": raw.get("mss_experts", False) is True,
        "exclude_from_trend": raw.get("exclude_from_trend", True) is not False,
        "lookback_weight_scale": float(raw.get("lookback_weight_scale", 0.25)),
        "record_scan": raw.get("record_scan", False) is not False,
    }


def apply_midday_macro_refresh(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """Force full macro/hot-news collection and persist to daily cache."""
    from agent_reach.daily_run.macro_collector import collect_macro_context, enrich_macro_sources
    from agent_reach.daily_run.snapshot_builder import load_portfolio
    from agent_reach.daily_run.snapshot_cache import load_daily_cache, save_daily_cache

    cfg = effective_settings(settings or load_settings())
    pf = snapshot.get("portfolio") or load_portfolio()
    macro_ctx = collect_macro_context(
        pf,
        config=config,
        settings=cfg,
        workflow="midday",
        scope="full",
    )
    sources = enrich_macro_sources(pf, macro_ctx.get("sources") or {}, cfg)

    out = dict(snapshot)
    out["macro_signals"] = dict(macro_ctx.get("macro_signals") or {})
    if macro_ctx.get("macro_summary"):
        out["macro_summary"] = macro_ctx["macro_summary"]
    merged_sources = dict(out.get("sources") or {})
    merged_sources.update(sources)
    out["sources"] = merged_sources

    live_bd = dict(macro_ctx.get("mss_breakdown") or {})
    if live_bd:
        from agent_reach.daily_run.intraday_scan_filters import merge_midday_breakdown

        base_bd = dict(out.get("mss_breakdown") or {})
        out["mss_breakdown"] = merge_midday_breakdown(base_bd, live_bd)

    cache = load_daily_cache()
    cache["macro_ctx"] = {
        "mss_breakdown": out.get("mss_breakdown"),
        "sources": out.get("sources"),
        "macro_summary": out.get("macro_summary"),
        "macro_signals": out.get("macro_signals"),
    }
    save_daily_cache(cache)
    return out


def _morning_session_lines(state: dict[str, Any], baseline: Optional[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if baseline:
        mss = baseline.get("mss_final") or (baseline.get("report") or {}).get("mss_final")
        verdict = baseline.get("verdict") or (baseline.get("report") or {}).get("verdict")
        if mss is not None or verdict:
            lines.append(f"- **08:00 早盘基线：** MSS **{mss or '—'}** · **{verdict or '—'}**")
    scans = list(state.get("scans") or [])
    if not scans:
        lines.append("- 上午尚无 intraday 扫描记录")
        return lines

    def _scan_num(scan_id: object) -> int | None:
        raw = str(scan_id or "").strip().upper()
        if raw.startswith("S") and raw[1:].isdigit():
            return int(raw[1:])
        return None

    am = [
        s
        for s in scans
        if str(s.get("source") or "") in {"morning", ""}
        or (_scan_num(s.get("scan_id")) is not None and _scan_num(s.get("scan_id")) <= 7)
    ]
    if not am:
        am = scans[:-1] if len(scans) > 1 else scans
    if am:
        last = am[-1]
        lines.append(
            f"- **上午末扫 {last.get('scan_id', '—')}：** MSS **{last.get('mss_final', '—')}** · "
            f"**{last.get('verdict', '—')}**"
        )
        if len(am) >= 2:
            first = am[0]
            lines.append(
                f"- **上午首扫 {first.get('scan_id', '—')}：** MSS **{first.get('mss_final', '—')}**"
            )
    return lines


def _build_macro_only_scan_result(
    enriched: dict[str, Any],
    st: Any,
    *,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Build midday card payload without appending an intraday MSS scan."""
    from agent_reach.daily_run.intraday_scan_filters import last_session_scan, scans_for_trend_detection
    from agent_reach.daily_run.lookback import compute_lookback_mss, detect_mss_trend
    from agent_reach.daily_run.macro_collector import fetch_intraday_xueqiu_cross_alerts

    scans = list(st.scans or [])
    session = last_session_scan(scans)
    lookback_mss, lookback_detail = compute_lookback_mss(scans, settings)
    trend = detect_mss_trend(scans, settings)
    anchor_trend = detect_mss_trend(scans_for_trend_detection(scans), settings)
    pf = enriched.get("portfolio") or {}
    xueqiu_cross = fetch_intraday_xueqiu_cross_alerts(pf, settings=settings)
    ref_id = session.get("scan_id") if session else "—"
    scan = {
        "scan_id": "12:30",
        "as_of": enriched.get("as_of"),
        "code": enriched.get("code") or (session or {}).get("code"),
        "name": enriched.get("name") or (session or {}).get("name"),
        "mss_final": (session or {}).get("mss_final"),
        "verdict": (session or {}).get("verdict") or "观察",
        "source": "midday_macro",
        "record_scan_skipped": True,
        "reference_scan_id": ref_id,
    }
    return {
        "scan": scan,
        "state": st.to_dict(),
        "lookback_mss": lookback_mss,
        "lookback_detail": lookback_detail,
        "trend": trend,
        "anchor_trend": anchor_trend,
        "xueqiu_cross": xueqiu_cross,
        "enriched": enriched,
        "macro_only": True,
    }


def render_midday_markdown(
    scan_result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    narrative: Optional[dict[str, Any]] = None,
) -> str:
    scan = scan_result.get("scan") or {}
    report = (scan_result.get("evaluation") or {}).get("report") or {}
    lookback_mss = scan_result.get("lookback_mss", 0)
    lookback_detail = scan_result.get("lookback_detail") or []
    trend = scan_result.get("trend") or "flat"
    anchor_trend = scan_result.get("anchor_trend") or trend
    state = scan_result.get("state") or {}
    enriched = scan_result.get("enriched") or {}
    xueqiu_cross = scan_result.get("xueqiu_cross") or {}
    macro_only = bool(scan_result.get("macro_only"))

    trend_map = {
        "rising": "上升",
        "falling": "下降",
        "turning_up": "拐点向上",
        "turning_down": "拐点向下",
        "flat": "横盘",
        "mixed": "震荡",
        "insufficient": "数据不足",
    }

    baseline = None
    try:
        from agent_reach.daily_run.workflows import load_morning_baseline

        baseline = load_morning_baseline()
    except (FileNotFoundError, OSError, ValueError):
        baseline = None

    ref_scan = scan.get("reference_scan_id") or "—"
    if macro_only:
        lines = [
            f"**☀️ 午盘宏观 refresh · {scan.get('scan_id', '12:30')}**",
            "",
            f"**参考 MSS（{ref_scan}）：** {scan.get('mss_final', '—')} 分 · **标签：** {scan.get('verdict', '—')}",
            f"**会话 Lookback MSS：** {lookback_mss} 分 · **趋势：** {trend_map.get(anchor_trend, anchor_trend)}",
            "",
            "**说明：** 12:30 不写入 intraday 扫描（11:30 停价）；仅刷新宏观/舆情，13:05 起常规扫描确认。",
        ]
    else:
        lines = [
            f"**☀️ 午盘分析 · {scan.get('scan_id', '—')}**",
            "",
            f"**即时 MSS：** {scan.get('mss_final', '—')} 分 · **标签：** {scan.get('verdict', '—')}",
            f"**Lookback MSS：** {lookback_mss} 分 · **趋势：** {trend_map.get(trend, trend)}",
        ]
        if scan.get("trend_excluded"):
            lines.append(
                "**说明：** 本扫描为午休锚点（11:30 停价），不参与拐点判定；"
                f"会话趋势 {trend_map.get(anchor_trend, anchor_trend)}，13:00 后扫描确认"
            )
    lines.extend(
        [
            "",
            "## 🌅 上午回顾",
            *_morning_session_lines(state, baseline),
            "",
            "## 🔄 午休宏观刷新",
        ]
    )
    macro_summary = str(enriched.get("macro_summary") or "").strip()
    if macro_summary:
        lines.append(f"- {macro_summary[:240]}")
    else:
        lines.append("- 宏观摘要未更新（检查网络 / 60s / 雪球 Cookie）")

    from agent_reach.daily_run.xueqiu_hot_display import render_intraday_xueqiu_alert_markdown

    alert_md = render_intraday_xueqiu_alert_markdown(xueqiu_cross)
    if alert_md:
        lines.extend(["", alert_md])

    lines.extend(["", "## 🎯 午后 Lookback"])
    if lookback_detail:
        for item in lookback_detail:
            src = ""
            for s in state.get("scans") or []:
                if s.get("scan_id") == item.get("scan_id"):
                    if s.get("source") == "midday":
                        src = " · 午盘"
                    elif s.get("source") == "morning":
                        src = " · 早盘"
                    break
            lines.append(
                f"- {item.get('scan_id')}{src}: MSS {item.get('mss_final')} × "
                f"{float(item.get('weight', 0)):.0%} = {item.get('weighted')}"
            )
    else:
        lines.append("- 数据不足")

    lines.extend(["", "## 📌 午后策略"])
    if macro_only:
        lines.append("- 13:05 开盘后以首个下午扫描（通常 S8）确认量价与 MSS 拐点")
    elif report.get("reasoning"):
        lines.append(f"- {report['reasoning']}")
    else:
        lines.append("- 13:00 开盘后以 S_n+1 扫描确认，Lookback 已含本午盘锚点")

    if narrative and not narrative.get("skipped"):
        from agent_reach.daily_run.report_narrative import render_narrative_markdown

        n_md = render_narrative_markdown(narrative, job="midday")
        if n_md.strip():
            lines.extend(["", n_md])

    footer = (
        "_说明：12:30 仅宏观/舆情 refresh，未写入 intraday MSS；13:05 起常规盘中扫描。_"
        if macro_only
        else "_说明：12:30 行情与 11:30 相同；本卡侧重午休资讯刷新与午后 Lookback 锚点，13:00 仍有一次常规盘中扫描。_"
    )
    lines.extend(["", footer])
    return "\n".join(lines)


def _midday_narrative_deterministic(
    scan: dict[str, Any],
    report: dict[str, Any],
    *,
    lookback_mss: float,
    trend: str,
    anchor_trend: Optional[str] = None,
) -> dict[str, Any]:
    focus: list[str] = []
    risks: list[str] = []
    verdict = str(scan.get("verdict") or report.get("verdict") or "观察")
    mss = scan.get("mss_final") or report.get("mss_final")
    session_trend = str(anchor_trend or trend)
    if scan.get("record_scan_skipped"):
        focus.append(f"会话 Lookback MSS {lookback_mss:.1f}（趋势 {session_trend}，12:30 未写入扫描）")
        ref = scan.get("reference_scan_id") or "上午末扫"
        if mss is not None:
            focus.append(f"参考 MSS {float(mss):.1f}（{ref}）· {verdict}")
        focus.append("13:05 起常规 intraday 扫描确认，勿仅凭午休资讯激进调仓")
        risks.append("12:30 不写入 MSS 扫描，午后决策以 S8+ 扫描为准")
    else:
        focus.append(f"午后 Lookback MSS {lookback_mss:.1f}（会话趋势 {session_trend}）")
        if mss is not None:
            focus.append(f"午盘即时 MSS {float(mss):.1f} · {verdict}")
        if scan.get("quote_stale"):
            focus.append("12:30 行情仍等于 11:30 收盘价，午休锚点仅刷新宏观/舆情")
        focus.append("13:00 开盘后关注量价确认，勿仅凭午休资讯激进调仓")
        if verdict in {"回避", "观察"} and session_trend in {"falling", "turning_down"}:
            risks.append("上午会话 MSS 未确认进攻，午后宜守现金或轻仓试探")
        elif scan.get("quote_stale") and session_trend not in {"falling", "turning_down"}:
            risks.append("午休锚点不参与拐点判定，午后以 S9+ 扫描为准")
    summary_verdict = verdict if not scan.get("record_scan_skipped") else f"宏观refresh·{verdict}"
    return {
        "summary": f"午盘 refresh · {summary_verdict} · Lookback {lookback_mss:.1f}",
        "focus_points": focus[:3],
        "divergence_notes": [],
        "risk_alerts": risks[:2],
        "planner": "deterministic",
        "skipped": False,
        "job": "midday",
    }


def run_midday(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    push: bool = True,
    title: Optional[str] = None,
    config=None,
) -> dict[str, Any]:
    """Midday macro refresh → evaluate → intraday scan (source=midday) → Feishu."""
    cfg = effective_settings(settings)
    mcfg = midday_cfg(cfg)
    if not mcfg["enabled"]:
        return {"steps": ["skipped"], "message": "midday disabled", "feishu": None}

    steps: list[str] = ["snapshot"]
    enriched = dict(snapshot)
    enriched.setdefault("report_type", "midday")
    enriched.setdefault("as_of", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())

    from agent_reach.daily_run.intraday import default_state_path, load_state
    from agent_reach.daily_run.intraday_scan_filters import last_session_scan, preserve_session_price_fields
    from agent_reach.daily_run.trade_calendar import is_lunch_break

    sym = enriched.get("code")
    st = load_state(default_state_path(sym) if sym else default_state_path(), code=sym)
    session_scan = last_session_scan(list(st.scans or []))
    if is_lunch_break() or mcfg.get("exclude_from_trend"):
        enriched = preserve_session_price_fields(enriched, session_scan)

    from agent_reach.daily_run.midday_cards import midday_card_layout_enabled

    card_layout = bool(mcfg.get("card_layout")) and midday_card_layout_enabled(cfg)

    if mcfg["macro_refresh"]:
        enriched = apply_midday_macro_refresh(enriched, settings=cfg, config=config)
        steps.append("macro_refresh")

    if mcfg["mss_experts"]:
        from agent_reach.daily_run.team import enrich_with_team_or_experts

        enriched, expert_steps = enrich_with_team_or_experts(
            enriched,
            cfg,
            workflow="intraday",
            skip_experts=False,
        )
        steps.extend(expert_steps or ["mss_experts"])

    evaluation: Optional[dict[str, Any]] = None
    if mcfg["record_scan"]:
        evaluation = evaluate_snapshot(enriched, cfg, doctor_channels=doctor_channels)
        steps.append("evaluate")

        from agent_reach.daily_run.intraday import record_scan_from_evaluation

        scan_result = record_scan_from_evaluation(
            enriched,
            evaluation,
            settings=cfg,
            source="midday",
        )
        scan_result["enriched"] = enriched
        scan_result["evaluation"] = evaluation
        steps.append("record_scan")
    else:
        scan_result = _build_macro_only_scan_result(enriched, st, settings=cfg)
        steps.append("macro_only")

    scan = scan_result.get("scan") or {}
    anchor_trend = scan_result.get("anchor_trend") or scan_result.get("trend") or "flat"
    narrative = _midday_narrative_deterministic(
        scan,
        (evaluation or {}).get("report") or {},
        lookback_mss=float(scan_result.get("lookback_mss") or 0),
        trend=str(scan_result.get("trend") or "flat"),
        anchor_trend=str(anchor_trend),
    )
    llm_cfg = (cfg.get("midday") or {}).get("llm_narrative") or {}
    if llm_cfg.get("enabled") is True and llm_cfg.get("planner") == "llm":
        from agent_reach.daily_run.report_narrative import generate_midday_narrative

        narrative = generate_midday_narrative(scan_result, settings=cfg)

    audit = (evaluation or {}).get("audit") if evaluation else None
    if audit is None and not mcfg["record_scan"]:
        from agent_reach.daily_run.auditor import run_data_audit

        audit = run_data_audit(enriched, cfg, doctor_channels=doctor_channels)

    from agent_reach.daily_run.midday_cards import (
        build_midday_card_context,
        render_midday_card_sections,
        render_midday_cards_markdown,
    )

    ctx = None
    if card_layout:
        ctx = build_midday_card_context(scan_result, settings=cfg, audit=audit, narrative=narrative)
        from agent_reach.daily_run.midday_handoff import build_midday_handoff, save_midday_handoff
        from agent_reach.daily_run.midday_content_scope import compute_halfday_pnl
        from agent_reach.daily_run.pm_session_overlay import build_pm_session_overlay_payload

        halfday = compute_halfday_pnl(
            portfolio=dict(enriched.get("portfolio") or {}),
            holdings_am_rows=list(ctx.holdings_am_rows or []),
        )
        red_count = sum(
            1
            for item in (ctx.anomaly_signal_items or [])
            if isinstance(item, dict) and str(item.get("severity") or "") == "red"
        )
        pm_overlay = build_pm_session_overlay_payload(
            scans=list((scan_result.get("state") or {}).get("scans") or []),
            settings=cfg,
            halfday_pnl_pct=halfday.get("halfday_pnl_pct"),
            red_anomaly_count=red_count,
            lookback_mss=scan_result.get("lookback_mss"),
            anchor_trend=scan_result.get("anchor_trend") or scan_result.get("trend"),
        )
        save_midday_handoff(
            build_midday_handoff(
                ctx,
                morning_handoff=ctx.morning_handoff,
                portfolio=dict(enriched.get("portfolio") or {}),
                enriched=enriched,
                pm_session_overlay=pm_overlay,
            )
        )
        steps.append("save_midday_handoff")
        steps.append("pm_session_overlay")
        markdown = render_midday_cards_markdown(ctx)
        steps.append("render_cards")
    else:
        markdown = render_midday_markdown(scan_result, settings=cfg, narrative=narrative)
        steps.append("render")
        if audit is not None and (not audit.passed or audit.warnings):
            warn_lines = ["**⚠️ 数据审计提示**"]
            if not audit.passed:
                warn_lines.append("；".join(audit.issues))
            for w in audit.warnings:
                warn_lines.append(f"- {w}")
            markdown = "\n".join(warn_lines) + "\n\n---\n\n" + markdown

    feishu_result = None
    push_error: Optional[str] = None
    if push:
        from agent_reach.config import Config
        from agent_reach.integrations.feishu import FeishuError, send_card
        from agent_reach.daily_run.report_push import push_report_sections, split_push_enabled

        cfg_obj = config or Config()
        tpl = cfg.get("report", {}).get("feishu_template_midday", "blue")
        name = scan.get("name") or scan.get("code") or "大盘"
        if card_layout and ctx is not None:
            sections = render_midday_card_sections(ctx)
            if split_push_enabled(cfg, report_kind="midday"):
                try:
                    feishu_result = push_report_sections(
                        sections,
                        settings=cfg,
                        config=cfg_obj,
                        report_type="midday",
                        fallback_title=title or f"☀️ 午盘 · {len(sections)}卡 · {name}",
                        template=tpl,
                        split=True,
                    )
                    steps.append("push_split")
                except FeishuError as exc:
                    push_error = str(exc)
            else:
                card_title = title or f"☀️ 午盘 · {len(sections)}卡 · {name}"
                try:
                    feishu_result = send_card(cfg_obj, card_title, markdown, template=tpl)
                    steps.append("push")
                except FeishuError as exc:
                    push_error = str(exc)
        else:
            if scan.get("record_scan_skipped"):
                card_title = title or f"☀️ 午盘宏观 refresh · 12:30 · {name}"
            else:
                card_title = title or f"☀️ 午盘分析 · {scan.get('scan_id', '—')} · {name}"
            try:
                feishu_result = send_card(cfg_obj, card_title, markdown, template=tpl)
                steps.append("push")
            except FeishuError as exc:
                push_error = str(exc)

    out: dict[str, Any] = {
        "steps": steps,
        "snapshot": enriched,
        "evaluation": evaluation,
        "scan_result": scan_result,
        "scan": scan,
        "lookback_mss": scan_result.get("lookback_mss"),
        "markdown": markdown,
        "llm_narrative": narrative,
        "midday_card_layout": card_layout,
        "feishu": feishu_result,
    }
    if push_error:
        out["push_error"] = push_error
    return out
