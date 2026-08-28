# -*- coding: utf-8
"""CLI handlers for daily-run berkshire subcommands."""

from __future__ import annotations

import json
from typing import Any


def cmd_berkshire(args) -> None:
    action = args.berkshire_action
    if action == "thesis":
        _cmd_thesis(args)
    elif action == "drift":
        _cmd_drift(args)
    elif action == "quality-screen":
        _cmd_quality_screen(args)
    elif action == "rigor":
        _cmd_rigor(args)
    else:
        raise SystemExit(f"unknown berkshire action: {action}")


def _cmd_thesis(args) -> None:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio
    from agent_reach.daily_run.berkshire.thesis_tracker import (
        load_thesis,
        render_thesis_markdown,
        sync_thesis_from_snapshot,
    )

    settings = load_settings()
    pf = load_portfolio()
    snap, _ = build_and_save(report_type="close", primary_code=args.code, portfolio=pf)
    if args.sync:
        result = sync_thesis_from_snapshot(snap, settings=settings, portfolio=pf, phase="close")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"✅ thesis {result.get('action')} → {result.get('path')}")
        return
    doc = load_thesis(args.code, settings)
    if doc is None:
        raise SystemExit(f"no thesis for {args.code}; run with --sync")
    text = render_thesis_markdown(doc)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(text)


def _cmd_drift(args) -> None:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio
    from agent_reach.daily_run.berkshire.thesis_drift import detect_thesis_drift, render_drift_markdown

    settings = load_settings()
    pf = load_portfolio()
    snap, _ = build_and_save(report_type="close", primary_code=args.code, portfolio=pf)
    report = detect_thesis_drift(args.code, snap, settings=settings)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_drift_markdown(report))


def _cmd_quality_screen(args) -> None:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio
    from agent_reach.daily_run.berkshire.quality_screen import screen_from_snapshot

    settings = load_settings()
    pf = load_portfolio()
    snap, _ = build_and_save(report_type="close", primary_code=args.code, portfolio=pf)
    result = screen_from_snapshot(snap)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        status = "✅ 通过" if result.passed else "❌ 未通过"
        print(f"{status} · {result.name} ({result.code}) — {result.reason}")


def _cmd_rigor(args) -> None:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio
    from agent_reach.daily_run.berkshire.financial_rigor import verify_snapshot_financials

    settings = load_settings()
    pf = load_portfolio()
    snap, _ = build_and_save(report_type="close", primary_code=args.code, portfolio=pf)
    checks = verify_snapshot_financials(snap)
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        mc = checks.get("market_cap") or {}
        if mc.get("skipped"):
            print(f"跳过市值验算：{mc.get('reason')}")
        else:
            print(mc.get("message", checks))
