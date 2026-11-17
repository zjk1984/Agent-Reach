# -*- coding: utf-8
"""Daily-run ops CLI — quant PM digest + project progress."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.dev_project_progress import (
    dev_project_progress_feishu_card,
    dev_project_progress_feishu_enabled,
    load_dev_project_progress_markdown,
    resolve_dev_project_progress_path,
)
from agent_reach.daily_run.project_progress import (
    load_and_build_project_progress,
    project_progress_feishu_card,
    project_progress_feishu_enabled,
    render_project_progress_markdown,
)
from agent_reach.daily_run.quant_digest import (
    load_and_build_quant_digest,
    quant_digest_feishu_card,
    render_quant_digest_markdown,
)
from agent_reach.daily_run.settings import load_settings


def add_ops_subparser(p_daily_sub: argparse._SubParsersAction) -> None:
    p_ops = p_daily_sub.add_parser("ops", help="Quant PM ops reports (digest, progress, health)")
    p_ops_sub = p_ops.add_subparsers(dest="ops_action", required=True)

    p_progress = p_ops_sub.add_parser(
        "project-progress",
        help="Daily 20:00 CST project progress (NAV, job_health, git HEAD) for Feishu",
    )
    p_progress.add_argument(
        "-o",
        "--output",
        default="",
        help="Write markdown to file (default: stdout only)",
    )
    p_progress.add_argument("--json", action="store_true", help="Print payload JSON instead of markdown")
    p_progress.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Feishu card body (markdown) only; do not send",
    )
    p_progress.add_argument(
        "--push",
        action="store_true",
        help="Push single Feishu summary card (requires ops.project_progress_feishu.enabled)",
    )

    p_dev = p_ops_sub.add_parser(
        "dev-project-progress",
        help="Daily 20:00 CST dev/coordinator progress (merged PRs, queue, blockers) for Feishu",
    )
    p_dev.add_argument(
        "--file",
        default="",
        help="Markdown report path (default: ~/.agent-reach/daily_run/reports/dev-project-progress.md)",
    )
    p_dev.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Feishu card body (markdown) only; do not send",
    )
    p_dev.add_argument(
        "--push",
        action="store_true",
        help="Push single Feishu card (requires ops.dev_project_progress_feishu.enabled)",
    )

    p_digest = p_ops_sub.add_parser(
        "quant-digest",
        help="Weekly performance digest (PnL, trades, job health, playbook delta)",
    )
    p_digest.add_argument(
        "--as-of",
        default="",
        help="ISO date for week anchor (default: today Shanghai)",
    )
    p_digest.add_argument(
        "-o",
        "--output",
        default="",
        help="Write markdown to file (default: stdout only)",
    )
    p_digest.add_argument("--json", action="store_true", help="Print payload JSON instead of markdown")
    p_digest.add_argument(
        "--push",
        action="store_true",
        help="Push single Feishu summary card (not full weekly close cards)",
    )

    p_recon = p_ops_sub.add_parser(
        "ledger-reconcile",
        help="Read-only ledger ↔ portfolio reconcile (default dry-run)",
    )
    p_recon.add_argument(
        "--as-of",
        default="",
        help="Reconcile as-of date (ISO, default: today Shanghai)",
    )
    p_recon.add_argument(
        "--ledger",
        default="",
        help="trade_ledger.jsonl path (default: ~/.agent-reach/daily_run/)",
    )
    p_recon.add_argument(
        "--portfolio",
        default="",
        help="portfolio.json path (default: ~/.agent-reach/daily_run/)",
    )
    p_recon.add_argument(
        "--focus",
        default="002583,000725",
        help="Comma-separated codes for cost/mark section (default: 002583,000725)",
    )
    p_recon.add_argument(
        "--mark-dates",
        default="2026-10-22,2026-10-23",
        help="Comma-separated dates for cost/mark probes",
    )
    p_recon.add_argument("--json", action="store_true", help="Print JSON payload instead of markdown")
    p_recon.add_argument(
        "--apply",
        action="store_true",
        help="Not implemented — reconcile is read-only; flag rejected if set",
    )


def cmd_ops(args: argparse.Namespace) -> None:
    action = args.ops_action
    settings = load_settings()

    if action == "project-progress":
        payload = load_and_build_project_progress(settings=settings)

        if args.dry_run:
            _title, body, _tpl = project_progress_feishu_card(payload)
            if args.json:
                print(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(body)
            return

        if args.json:
            print(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2))
        else:
            md = render_project_progress_markdown(payload)
            out_path = Path(args.output).expanduser() if args.output else None
            if out_path:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(md, encoding="utf-8")
                print(f"✅ progress written: {out_path}", file=sys.stderr)
            else:
                print(md)

        if args.push:
            if not project_progress_feishu_enabled(settings):
                print(
                    "⏭ project-progress Feishu skipped: ops.project_progress_feishu.enabled is false",
                    file=sys.stderr,
                )
                return
            from agent_reach.config import Config
            from agent_reach.integrations.feishu import FeishuError, feishu_mode, send_card

            if feishu_mode(Config()) is None:
                print("❌ Feishu push failed: not configured", file=sys.stderr)
                sys.exit(1)

            title, body, tpl = project_progress_feishu_card(payload)
            try:
                send_card(Config(), title, body, template=tpl)
                print("✅ Feishu project-progress card sent", file=sys.stderr)
            except FeishuError as exc:
                print(f"❌ Feishu push failed: {exc}", file=sys.stderr)
                sys.exit(1)
        return

    if action == "dev-project-progress":
        path = resolve_dev_project_progress_path(args.file or None)
        try:
            md = load_dev_project_progress_markdown(path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"❌ dev-project-progress: {exc}", file=sys.stderr)
            sys.exit(1)

        title, body, tpl = dev_project_progress_feishu_card(md)

        if args.dry_run:
            print(body)
            return

        if not args.push:
            print(md)
            return

        if not dev_project_progress_feishu_enabled(settings):
            print(
                "⏭ dev-project-progress Feishu skipped: "
                "ops.dev_project_progress_feishu.enabled is false",
                file=sys.stderr,
            )
            return

        from agent_reach.config import Config
        from agent_reach.integrations.feishu import FeishuError, feishu_mode, send_card

        if feishu_mode(Config()) is None:
            print("❌ Feishu push failed: not configured", file=sys.stderr)
            sys.exit(1)

        try:
            send_card(Config(), title, body, template=tpl)
            print(f"✅ Feishu dev-project-progress card sent ({path})", file=sys.stderr)
        except FeishuError as exc:
            print(f"❌ Feishu push failed: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if action == "quant-digest":
        as_of: Optional[date] = date.fromisoformat(args.as_of) if args.as_of else None
        payload = load_and_build_quant_digest(as_of=as_of, settings=settings)

        if args.json:
            print(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2))
        else:
            md = render_quant_digest_markdown(payload)
            out_path = Path(args.output).expanduser() if args.output else None
            if out_path:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(md, encoding="utf-8")
                print(f"✅ digest written: {out_path}")
            else:
                print(md)

        if args.push:
            from agent_reach.config import Config
            from agent_reach.integrations.feishu import FeishuError, send_card

            title, body, tpl = quant_digest_feishu_card(payload)
            try:
                send_card(Config(), title, body, template=tpl)
                print("✅ Feishu digest card sent", file=sys.stderr)
            except FeishuError as exc:
                print(f"❌ Feishu push failed: {exc}", file=sys.stderr)
                sys.exit(1)
        return

    if action == "ledger-reconcile":
        if args.apply:
            print("❌ ledger-reconcile is read-only; omit --apply", file=sys.stderr)
            sys.exit(2)
        from agent_reach.daily_run.ledger_reconcile import render_ledger_reconcile_markdown, run_ledger_reconcile

        as_of: Optional[date] = date.fromisoformat(args.as_of) if args.as_of else None
        ledger_path = Path(args.ledger).expanduser() if args.ledger else None
        portfolio_path = Path(args.portfolio).expanduser() if args.portfolio else None
        focus = [c.strip() for c in str(args.focus).split(",") if c.strip()]
        mark_dates = [date.fromisoformat(d.strip()) for d in str(args.mark_dates).split(",") if d.strip()]
        result = run_ledger_reconcile(
            as_of=as_of,
            settings=settings,
            ledger_path=ledger_path,
            portfolio_path=portfolio_path,
            focus_codes=focus,
            mark_dates=mark_dates,
            dry_run=True,
        )
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_ledger_reconcile_markdown(result))
        sys.exit(0 if result.ok else 1)
        return

    print(f"Unknown ops action: {action}")
    sys.exit(1)
