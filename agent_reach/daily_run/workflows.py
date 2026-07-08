# -*- coding: utf-8
"""One-click morning / close workflows for daily_run_skill."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.pipeline import evaluate_snapshot, render_markdown
from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.team import render_team_markdown, run_team_first
from agent_reach.daily_run.verify import render_verify_markdown, verify_snapshots


def _default_baseline_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "last_morning.json"


def run_morning(
    snapshot: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    doctor_channels: Optional[dict[str, dict]] = None,
    plugin_names: Optional[list[str]] = None,
    team_first: bool = True,
    push: bool = True,
    start_notify: bool = True,
    title: Optional[str] = None,
    config=None,
) -> dict[str, Any]:
    """
    Full morning pipeline:
    start notify → Team-First 8 experts → audit/verdict/gate → Feishu push
    """
    cfg = settings or load_settings()
    steps: list[str] = []

    if start_notify and push:
        _send_start_notification(config, cfg)
        steps.append("start_notify")

    snapshot = dict(snapshot)
    snapshot.setdefault("report_type", "premarket")
    snapshot.setdefault("as_of", datetime.now(timezone.utc).isoformat())

    if team_first:
        enriched = run_team_first(snapshot, cfg, names=plugin_names)
        steps.append("team_first")
    else:
        from agent_reach.daily_run.plugins.loader import run_experts

        enriched = run_experts(snapshot, cfg, names=plugin_names)
        steps.append("experts")

    evaluation = evaluate_snapshot(enriched, cfg, doctor_channels=doctor_channels)
    steps.append("evaluate")

    audit = evaluation["audit"]
    gate = evaluation["gate"]
    report = evaluation["report"]

    feishu_result = None
    if push:
        if not audit.passed:
            raise RuntimeError(f"数据审计未通过：{audit.summary()}")
        if not gate.passed:
            raise RuntimeError(f"质量门禁未通过：{gate.summary()}")
        card_title = title or _morning_title(report)
        body = render_team_markdown(enriched) + "\n\n---\n\n" + render_markdown(report)
        feishu_result = _push_markdown(card_title, body, cfg, config, report_type="premarket")
        steps.append("push")

    return {
        "steps": steps,
        "snapshot": enriched,
        "evaluation": evaluation,
        "markdown": render_team_markdown(enriched) + "\n\n---\n\n" + render_markdown(report),
        "team_markdown": render_team_markdown(enriched),
        "feishu": feishu_result,
    }


def run_close(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
    plugin_names: Optional[list[str]] = None,
    team_first: bool = True,
    push: bool = True,
    title: Optional[str] = None,
    config=None,
) -> dict[str, Any]:
    """Close workflow: Team-First experts → verify baseline vs current → Feishu push."""
    cfg = settings or load_settings()
    current = dict(current)
    current.setdefault("report_type", "close")

    enriched = current
    team_md = ""
    if team_first:
        enriched = run_team_first(current, cfg, names=plugin_names)
        team_md = render_team_markdown(enriched)

    verify = verify_snapshots(baseline, enriched, cfg)
    md = (team_md + "\n\n---\n\n" if team_md else "") + render_verify_markdown(verify)

    feishu_result = None
    if push:
        from agent_reach.config import Config

        cfg_obj = config or Config()
        tpl = cfg.get("report", {}).get("feishu_template_verify", "purple")
        card_title = title or f"🧠 收盘复盘 · {verify.name or verify.code or '大盘'}"
        feishu_result = _push_markdown(card_title, md, cfg, cfg_obj, template=tpl)

    return {
        "verify": verify.to_dict(),
        "snapshot": enriched,
        "markdown": md,
        "team_markdown": team_md,
        "feishu": feishu_result,
    }


def save_morning_baseline(snapshot: dict[str, Any], path: Optional[Path] = None) -> Path:
    """Persist morning snapshot for later close verification."""
    import json

    out = path or _default_baseline_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_morning_baseline(path: Optional[Path] = None) -> dict[str, Any]:
    import json

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
        "**股票大师 daily_run_skill · Team-First**\n\n"
        "正在执行：**8 专家并行** → 数据审计 → MSS 决策 → Supervisor 仲裁 → 飞书推送\n\n"
        "预计完成时间：**3–5 分钟**",
        template=tpl,
    )
