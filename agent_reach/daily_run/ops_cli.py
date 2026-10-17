# -*- coding: utf-8
"""Daily-run ops CLI — quant PM weekly digest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.quant_digest import (
    load_and_build_quant_digest,
    quant_digest_feishu_card,
    render_quant_digest_markdown,
)
from agent_reach.daily_run.settings import load_settings


def add_ops_subparser(p_daily_sub: argparse._SubParsersAction) -> None:
    p_ops = p_daily_sub.add_parser("ops", help="Quant PM ops reports (digest, health)")
    p_ops_sub = p_ops.add_subparsers(dest="ops_action", required=True)

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


def cmd_ops(args: argparse.Namespace) -> None:
    action = args.ops_action
    settings = load_settings()

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

    print(f"Unknown ops action: {action}")
    sys.exit(1)
