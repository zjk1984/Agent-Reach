# -*- coding: utf-8
"""CLI: daily-run storage status / backfill / distill / query."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_reach.daily_run.settings import load_settings, save_user_settings, user_settings_path


def add_storage_subparser(p_daily_sub: argparse._SubParsersAction) -> None:
    p_store = p_daily_sub.add_parser(
        "storage",
        help="Persist trades/portfolio/harness/experience to SQLite (TencentDB-inspired layers)",
    )
    p_store_sub = p_store.add_subparsers(dest="storage_action", required=True)

    p_status = p_store_sub.add_parser("status", help="Show DB path, schema version, row counts")
    p_status.add_argument("--json", action="store_true", help="JSON output")

    p_enable = p_store_sub.add_parser("enable", help="Enable SQLite dual-write in user settings")
    p_enable.add_argument(
        "--backend",
        choices=["sqlite", "postgres"],
        default="sqlite",
        help="Storage backend (default: sqlite)",
    )

    p_backfill = p_store_sub.add_parser("backfill", help="Import existing JSON/JSONL artifacts")
    p_backfill.add_argument(
        "--force",
        action="store_true",
        help="Drop and recreate SQLite DB before backfill",
    )
    p_backfill.add_argument("--root", default="", help="Override ~/.agent-reach/daily_run root")

    p_distill = p_store_sub.add_parser("distill", help="Run L0→L1 distillation on pending events")
    p_distill.add_argument("--limit", type=int, default=500, help="Max L0 events per run")

    p_query = p_store_sub.add_parser("query", help="Query stored trades or L1 atoms")
    p_query.add_argument(
        "target",
        choices=["trades", "atoms", "events"],
        help="Query target",
    )
    p_query.add_argument("--code", default="", help="Filter by stock code")
    p_query.add_argument("--kind", default="", help="Filter events/atoms by kind")
    p_query.add_argument("--since", default="", help="ISO date/time lower bound")
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--json", action="store_true", help="JSON output")

    p_prune = p_store_sub.add_parser(
        "prune",
        help="Retention cleanup for caches/logs/runs and distilled L0 payloads",
    )
    p_prune.add_argument("--dry-run", action="store_true", help="Preview deletions only")
    p_prune.add_argument("--runs-keep-days", type=int, default=60, help="Keep run manifests (default 60)")
    p_prune.add_argument("--cache-keep-days", type=int, default=14, help="Keep daily cache files (default 14)")
    p_prune.add_argument("--log-keep-days", type=int, default=30, help="Keep cron logs (default 30)")
    p_prune.add_argument("--l0-keep-days", type=int, default=90, help="Keep distilled L0 payloads (default 90)")
    p_prune.add_argument("--vacuum", action="store_true", help="VACUUM SQLite after L0 prune")
    p_prune.add_argument("--root", default="", help="Override ~/.agent-reach/daily_run root")
    p_prune.add_argument("--json", action="store_true", help="JSON output")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_storage(args: argparse.Namespace) -> None:
    action = args.storage_action
    settings = load_settings()

    if action == "enable":
        data = dict(settings)
        block = dict(data.get("storage") or {})
        block["enabled"] = True
        block["backend"] = args.backend
        block.setdefault("dual_write", True)
        block.setdefault(
            "distill",
            {"enabled": True, "auto_after_close": False},
        )
        data["storage"] = block
        path = save_user_settings(data)
        print(f"✅ storage enabled ({args.backend}) → {path}")
        print("Run: python3 -m agent_reach.cli daily-run storage backfill")
        return

    from agent_reach.daily_run.storage import get_store, storage_enabled

    if action == "status":
        if not storage_enabled(settings):
            print("storage: disabled (run `daily-run storage enable` or set storage.enabled=true)")
            sys.exit(0)
        status = get_store(settings).status()
        if args.json:
            _print_json(status)
        else:
            print(f"backend: {status.get('backend')}")
            print(f"path: {status.get('path') or status.get('dsn')}")
            print(f"schema: {status.get('schema_version')}")
            print(f"undistilled L0: {status.get('undistilled_l0')}")
            for key, val in sorted((status.get("counts") or {}).items()):
                print(f"  {key}: {val}")
        return

    if not storage_enabled(settings):
        print("❌ storage disabled — run: python3 -m agent_reach.cli daily-run storage enable")
        sys.exit(1)

    if action == "backfill":
        from agent_reach.daily_run.storage.backfill import backfill_from_files
        from pathlib import Path

        root = Path(args.root).expanduser() if args.root else None
        result = backfill_from_files(root=root, force=args.force, settings=settings)
        _print_json(result)
        return

    if action == "distill":
        from agent_reach.daily_run.storage.distill import run_distill

        result = run_distill(limit=max(1, int(args.limit)), settings=settings)
        _print_json(result)
        return

    if action == "prune":
        from pathlib import Path

        from agent_reach.daily_run.storage.prune import run_prune

        root = Path(args.root).expanduser() if args.root else None
        result = run_prune(
            settings=settings,
            root=root,
            runs_keep_days=max(1, int(args.runs_keep_days)),
            cache_keep_days=max(1, int(args.cache_keep_days)),
            log_keep_days=max(1, int(args.log_keep_days)),
            l0_keep_days=max(1, int(args.l0_keep_days)),
            vacuum=bool(args.vacuum),
            dry_run=bool(args.dry_run),
        )
        if args.json:
            _print_json(result)
            return
        files = result.get("files") or {}
        db = result.get("database") or {}
        print(f"files: {files.get('items', 0)} items, {files.get('mb_freed', 0)} MB freed")
        if db.get("skipped"):
            print(f"database: skipped ({db.get('reason')})")
        else:
            print(
                f"database: {db.get('deleted_rows', db.get('would_delete_rows', 0))} L0 rows, "
                f"~{round((db.get('bytes_estimate') or 0) / 1024 / 1024, 2)} MB"
            )
            if db.get("vacuum_bytes_freed") is not None:
                print(f"vacuum: {round(db['vacuum_bytes_freed'] / 1024 / 1024, 2)} MB freed")
        return

    if action == "query":
        store = get_store(settings)
        if args.target == "trades":
            rows = store.query_trades(code=args.code, since=args.since, limit=max(1, int(args.limit)))
        elif args.target == "atoms":
            rows = store.query_l1_atoms(
                kind=args.kind,
                code=args.code,
                since=args.since,
                limit=max(1, int(args.limit)),
            )
        else:
            rows = store.query_l0_events(
                kind=args.kind,
                since=args.since,
                limit=max(1, int(args.limit)),
            )
        if args.json:
            _print_json(rows)
            return
        if not rows:
            print("(no rows)")
            return
        for row in rows:
            if args.target == "trades":
                act = row.get("action") or {}
                print(
                    f"{row.get('at')} {row.get('trade_id')} "
                    f"{act.get('side')} {act.get('code')} {act.get('shares')}@{act.get('price')}"
                )
            elif args.target == "atoms":
                print(f"{row.get('at')} [{row.get('kind')}] {row.get('title')}: {row.get('content')[:120]}")
            else:
                print(f"{row.get('at')} [{row.get('kind')}] id={row.get('id')}")
        return

    print(f"Unknown storage action: {action}")
    sys.exit(1)
