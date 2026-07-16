# -*- coding: utf-8
"""One-click morning / close workflows for daily_run_skill."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.pipeline import evaluate_snapshot, render_markdown
from agent_reach.daily_run.report_push import (
    push_report_sections,
    render_close_sections,
    render_morning_sections,
    split_push_enabled,
)
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.close_research import render_research_markdown, run_exa_research
from agent_reach.daily_run.curve_analysis import analyze_intraday_curve, render_curve_markdown
from agent_reach.daily_run.experience import append_experience_entry, render_experience_markdown
from agent_reach.daily_run.team import (
    experts_enabled,
    render_team_markdown,
    run_team_first,
    team_first_enabled,
)
from agent_reach.daily_run.verify import render_verify_markdown, verify_snapshots


def _default_baseline_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "last_morning.json"


def _attach_intraday_scans(snapshot: dict[str, Any], *, code: Optional[str] = None) -> dict[str, Any]:
    """Merge today's intraday scans into close snapshot (source of truth)."""
    from agent_reach.daily_run.intraday import load_state

    enriched = dict(snapshot)
    sym = code or enriched.get("code")
    state = load_state(code=sym)
    if not state.scans:
        return enriched
    enriched["intraday_scans"] = state.scans
    enriched["mss_intraday_actual"] = [
        float(s["mss_final"]) for s in state.scans if s.get("mss_final") is not None
    ]
    return enriched


def run_morning(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    plugin_names: Optional[list[str]] = None,
    team_first: Optional[bool] = None,
    push: bool = True,
    start_notify: bool = True,
    title: Optional[str] = None,
    config=None,
) -> dict[str, Any]:
    """
    Full morning pipeline:
    snapshot → audit/verdict/gate → Feishu push
    """
    cfg = settings or load_settings()
    steps: list[str] = []

    if start_notify and push:
        _send_start_notification(config, cfg)
        steps.append("start_notify")

    snapshot = dict(snapshot)
    snapshot.setdefault("report_type", "premarket")
    snapshot.setdefault("as_of", datetime.now(timezone.utc).isoformat())

    if team_first is None:
        use_team = team_first_enabled(cfg, workflow="morning")
    else:
        use_team = bool(team_first) and experts_enabled(cfg, workflow="morning")

    if use_team:
        enriched = run_team_first(snapshot, cfg, names=plugin_names)
        steps.append("team_first")
    elif experts_enabled(cfg, workflow="morning"):
        from agent_reach.daily_run.plugins.loader import run_experts

        enriched = run_experts(snapshot, cfg, names=plugin_names)
        steps.append("experts")
    else:
        enriched = dict(snapshot)
        steps.append("snapshot")

    evaluation = evaluate_snapshot(enriched, cfg, doctor_channels=doctor_channels)
    steps.append("evaluate")

    audit = evaluation["audit"]
    gate = evaluation["gate"]
    report = evaluation["report"]

    if not audit.passed:
        raise RuntimeError(f"数据审计未通过：{audit.summary()}")
    if not gate.passed:
        raise RuntimeError(f"质量门禁未通过：{gate.summary()}")

    team_md = render_team_markdown(enriched) if experts_enabled(cfg, workflow="morning") else ""
    report_md = render_markdown(report)
    feishu_result = None
    if push:
        sections = render_morning_sections(
            team_markdown=team_md,
            report_markdown=report_md,
            report=report,
        )
        feishu_result = push_report_sections(
            sections,
            settings=cfg,
            config=config,
            report_type="premarket",
            fallback_title=title or _morning_title(report),
            split=split_push_enabled(cfg, report_kind="morning"),
        )
        steps.append("push")
        if feishu_result.get("mode") == "split":
            steps.append(f"push_split_{feishu_result.get('count', 0)}")

    return {
        "steps": steps,
        "snapshot": enriched,
        "evaluation": evaluation,
        "markdown": team_md + "\n\n---\n\n" + report_md,
        "team_markdown": team_md,
        "report_markdown": report_md,
        "feishu": feishu_result,
    }


def run_close(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    plugin_names: Optional[list[str]] = None,
    team_first: Optional[bool] = None,
    push: bool = True,
    title: Optional[str] = None,
    config=None,
) -> dict[str, Any]:
    """Close workflow: Team-First experts → verify baseline vs current → Feishu push."""
    cfg = settings or load_settings()
    current = _attach_intraday_scans(dict(current), code=current.get("code"))
    current.setdefault("report_type", "close")

    enriched = current
    team_md = ""
    if team_first is None:
        use_team = team_first_enabled(cfg, workflow="close")
    else:
        use_team = bool(team_first) and experts_enabled(cfg, workflow="close")
    if use_team:
        enriched = run_team_first(current, cfg, names=plugin_names)
        team_md = render_team_markdown(enriched)

    verify = verify_snapshots(baseline, enriched, cfg)
    verify_dict = verify.to_dict()

    curve = None
    curve_md = ""
    mss_actual = enriched.get("mss_intraday_actual") or []
    scan_ids = [str(s.get("scan_id") or f"S{i + 1}") for i, s in enumerate(enriched.get("intraday_scans") or [])]
    if mss_actual:
        pred = baseline.get("mss_range")
        pred_tuple = (float(pred[0]), float(pred[1])) if pred and len(pred) == 2 else None
        curve = analyze_intraday_curve(
            [float(x) for x in mss_actual if x is not None],
            predicted_range=pred_tuple,
            scan_ids=scan_ids or None,
        )
        curve_md = render_curve_markdown(curve)

    research_results = run_exa_research(enriched, cfg)
    research_md = render_research_markdown(enriched, research_results=research_results, settings=cfg) or ""

    exp_path = append_experience_entry(
        enriched, verify_dict, curve=curve, research=research_results, settings=cfg
    )
    exp_md = render_experience_markdown(limit=3) or ""

    verify_md = render_verify_markdown(verify)

    from agent_reach.daily_run.auditor import run_data_audit

    audit = run_data_audit(enriched, cfg)
    audit_lines: list[str] = []
    if not audit.passed:
        audit_lines.append(f"**数据审计未通过：** {'；'.join(audit.issues)}")
    if audit.warnings:
        audit_lines.append("**审计警告：**")
        audit_lines.extend(f"- {w}" for w in audit.warnings)
    if audit_lines:
        audit_block = "\n".join(audit_lines)
        verify_md = audit_block + ("\n\n---\n\n" + verify_md if verify_md else "")

    md = "\n\n---\n\n".join(
        p for p in [team_md, curve_md, research_md, exp_md, verify_md] if p
    )

    feishu_result = None
    if push:
        audit_cfg = cfg.get("data_audit", {})
        if not audit.passed and audit_cfg.get("close_block_on_audit_fail", True):
            raise RuntimeError(f"收盘数据审计未通过：{audit.summary()}")

        from agent_reach.config import Config

        cfg_obj = config or Config()
        sections = render_close_sections(
            verify_name=verify.name or verify.code or "大盘",
            team_markdown=team_md,
            curve_markdown=curve_md,
            research_markdown=research_md or "",
            experience_markdown=exp_md or "",
            verify_markdown=verify_md,
        )
        feishu_result = push_report_sections(
            sections,
            settings=cfg,
            config=cfg_obj,
            report_type="verify",
            fallback_title=title or f"🧠 收盘复盘 · {verify.name or verify.code or '大盘'}",
            template=cfg.get("report", {}).get("feishu_template_verify", "purple"),
            split=split_push_enabled(cfg, report_kind="close"),
        )

    return {
        "verify": verify_dict,
        "snapshot": enriched,
        "markdown": md,
        "team_markdown": team_md,
        "curve_markdown": curve_md,
        "research_markdown": research_md,
        "experience_markdown": exp_md,
        "verify_markdown": verify_md,
        "research": research_results,
        "experience_path": str(exp_path),
        "feishu": feishu_result,
        "audit": {
            "passed": audit.passed,
            "issues": audit.issues,
            "warnings": audit.warnings,
        },
    }


def morning_baseline_path(code: str) -> Path:
    from agent_reach.daily_run.snapshot_builder import _normalize_code

    norm = _normalize_code(str(code))
    return Path.home() / ".agent-reach" / "daily_run" / "baselines" / "morning" / f"{norm}.json"


def save_morning_baseline(
    snapshot: dict[str, Any],
    path: Optional[Path] = None,
    *,
    code: Optional[str] = None,
    primary_code: Optional[str] = None,
) -> Path:
    """Persist morning snapshot for later close verification."""
    import json

    from agent_reach.daily_run.snapshot_builder import _normalize_code

    norm = _normalize_code(str(code or snapshot.get("code") or ""))
    written: Optional[Path] = None
    if norm and norm != "MARKET":
        out = morning_baseline_path(norm)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = out

    pc = _normalize_code(str(primary_code)) if primary_code else None
    if path is not None or (pc and norm == pc):
        legacy = path or _default_baseline_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return legacy
    if written:
        return written
    out = path or _default_baseline_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_morning_baseline(path: Optional[Path] = None, *, code: Optional[str] = None) -> dict[str, Any]:
    import json

    from agent_reach.daily_run.snapshot_builder import _normalize_code

    if code:
        norm = _normalize_code(str(code))
        per = morning_baseline_path(norm)
        if per.exists():
            return json.loads(per.read_text(encoding="utf-8"))
        legacy = _default_baseline_path()
        if legacy.exists():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if _normalize_code(str(data.get("code", ""))) == norm:
                return data
        raise FileNotFoundError(
            f"未找到 {norm} 的早盘基线：{per}，请先运行 daily-run morning --save-baseline"
        )

    p = path or _default_baseline_path()
    if not p.exists():
        raise FileNotFoundError(f"未找到早盘基线：{p}，请先运行 daily-run morning --save-baseline")
    return json.loads(p.read_text(encoding="utf-8"))


def _morning_title(report: dict[str, Any]) -> str:
    name = report.get("name") or report.get("code") or "大盘"
    verdict = report.get("verdict", "")
    return f"🌅 股票大师 · {name} · {verdict}"


def _push_markdown(
    title: str,
    markdown: str,
    settings: dict[str, Any],
    config,
    *,
    report_type: str = "premarket",
    template: Optional[str] = None,
) -> dict[str, Any]:
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import send_card

    cfg_obj = config or Config()
    templates = settings.get("report", {})
    tpl = template or templates.get(f"feishu_template_{report_type}", "blue")
    return send_card(cfg_obj, title, markdown, template=tpl)


def _send_start_notification(config, settings: dict[str, Any]) -> None:
    from agent_reach.config import Config
    from agent_reach.integrations.feishu import send_card

    cfg = config or Config()
    tpl = settings.get("report", {}).get("feishu_template_premarket", "orange")
    send_card(
        cfg,
        "🌅 早盘分析已启动",
        "**股票大师 daily_run_skill**\n\n"
        "正在执行：**数据审计** → **MSS 决策** → 飞书推送\n\n"
        "预计完成时间：**1–3 分钟**",
        template=tpl,
    )


def run_weekly(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    title: Optional[str] = None,
    config=None,
    portfolio: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Saturday weekly summary: PnL, holdings, watchlist, hot sectors → Feishu."""
    from agent_reach.daily_run.weekly_digest import save_weekly_digest
    from agent_reach.daily_run.weekly_report import (
        generate_weekly_report,
        render_weekly_markdown,
        weekly_report_title,
    )

    cfg = settings or load_settings()
    weekly_cfg = cfg.get("weekly_report") or {}
    if weekly_cfg.get("enabled", True) is False:
        return {"steps": ["skipped"], "message": "weekly_report disabled", "feishu": None}

    steps: list[str] = ["generate"]
    report = generate_weekly_report(snapshot, cfg, portfolio=portfolio)
    digest_path = save_weekly_digest(report.to_dict())
    steps.append("digest")
    md = render_weekly_markdown(report)
    steps.append("render")

    feishu_result = None
    if push:
        from agent_reach.config import Config

        from agent_reach.daily_run.report_push import (
            push_report_sections,
            render_weekly_push_sections,
            split_push_enabled,
        )

        cfg_obj = config or Config()
        sections = render_weekly_push_sections(report)
        feishu_result = push_report_sections(
            sections,
            settings=cfg,
            config=cfg_obj,
            report_type="weekly",
            fallback_title=title or weekly_report_title(report),
            template=cfg.get("report", {}).get("feishu_template_weekly", "blue"),
            split=split_push_enabled(cfg, report_kind="weekly"),
        )
        steps.append("push")
        if feishu_result.get("mode") == "split":
            steps.append(f"push_split_{feishu_result.get('count', 0)}")

    return {
        "steps": steps,
        "report": report.to_dict(),
        "digest_path": str(digest_path),
        "markdown": md,
        "feishu": feishu_result,
    }


def run_forecast(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    title: Optional[str] = None,
    config=None,
    portfolio: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Sunday next-week forecast: MSS paths, symbols, news → Feishu."""
    from agent_reach.daily_run.week_forecast import (
        forecast_title,
        generate_week_forecast,
        persist_week_forecast,
        render_forecast_markdown,
    )

    cfg = settings or load_settings()
    wf_cfg = cfg.get("week_forecast") or {}
    if wf_cfg.get("enabled", True) is False:
        return {"steps": ["skipped"], "message": "week_forecast disabled", "feishu": None}

    steps: list[str] = ["generate"]
    forecast = generate_week_forecast(snapshot, cfg, portfolio=portfolio)
    path = persist_week_forecast(forecast)
    steps.append("persist")

    md = render_forecast_markdown(forecast)
    steps.append("render")

    feishu_result = None
    if push:
        from agent_reach.config import Config

        from agent_reach.daily_run.report_push import (
            push_report_sections,
            render_forecast_push_sections,
            split_push_enabled,
        )

        cfg_obj = config or Config()
        sections = render_forecast_push_sections(forecast)
        feishu_result = push_report_sections(
            sections,
            settings=cfg,
            config=cfg_obj,
            report_type="forecast",
            fallback_title=title or forecast_title(forecast),
            template=cfg.get("report", {}).get("feishu_template_forecast", "blue"),
            split=split_push_enabled(cfg, report_kind="forecast"),
        )
        steps.append("push")
        if feishu_result.get("mode") == "split":
            steps.append(f"push_split_{feishu_result.get('count', 0)}")

    return {
        "steps": steps,
        "forecast": forecast.to_dict(),
        "forecast_path": str(path),
        "markdown": md,
        "feishu": feishu_result,
    }
