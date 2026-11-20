# -*- coding: utf-8
"""08:05 one-shot morning retry when the 08:00 manifest is FAIL or incomplete."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

_SH_TZ = ZoneInfo("Asia/Shanghai")
MORNING_CATCHUP_ENV = "AGENT_REACH_MORNING_CATCHUP"


def morning_catchup_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "daily-run-morning-catchup.sh"


def _morning_catchup_cfg(settings: dict[str, Any]) -> dict[str, Any]:
    raw = (settings.get("ops") or {}).get("morning_catchup") or {}
    push = raw.get("push")
    if push is None:
        push = raw.get("push_feishu", True)
    return {"enabled": raw.get("enabled") is not False, "push": push is not False}


def _list_morning_manifests_today() -> list[tuple[str, dict[str, Any]]]:
    from agent_reach.daily_run.run_manifest import runs_dir
    from agent_reach.daily_run.trade_calendar import today_shanghai

    day = today_shanghai().isoformat()
    out_dir = runs_dir() / day
    if not out_dir.is_dir():
        return []
    rows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(out_dir.glob("morning_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(record, dict):
            rows.append((path.stem, record))
    return rows


def is_morning_catchup_manifest(record: dict[str, Any]) -> bool:
    payload = record.get("payload") or {}
    if payload.get("morning_catchup"):
        return True
    meta = payload.get("schedule_meta") or {}
    return bool(meta.get("morning_catchup"))


def primary_morning_manifest_today() -> Optional[dict[str, Any]]:
    """Latest non-catchup morning manifest for today."""
    rows = _list_morning_manifests_today()
    primary = [rec for _stem, rec in rows if not is_morning_catchup_manifest(rec)]
    if not primary:
        return None
    return primary[-1]


def has_morning_catchup_today() -> bool:
    return any(is_morning_catchup_manifest(rec) for _stem, rec in _list_morning_manifests_today())


def _eval_bool_passed(node: Any) -> Optional[bool]:
    if node is None:
        return None
    if isinstance(node, dict):
        if "passed" in node:
            return bool(node.get("passed"))
        return None
    passed = getattr(node, "passed", None)
    if passed is None:
        return None
    return bool(passed)


def morning_manifest_needs_catchup(record: Optional[dict[str, Any]]) -> tuple[bool, str]:
    """True when playbook L1-B should fire (FAIL or incomplete)."""
    if record is None:
        return True, "no morning manifest today (incomplete)"

    payload = record.get("payload") or {}
    if payload.get("skipped"):
        reason = str(payload.get("reason") or "morning skipped")
        return True, reason

    if payload.get("error"):
        err = str(payload.get("error"))
        return True, f"morning error: {err[:120]}"

    evaluation = payload.get("evaluation") or {}
    audit_ok = _eval_bool_passed(evaluation.get("audit"))
    if audit_ok is False:
        return True, "morning audit failed"

    gate_ok = _eval_bool_passed(evaluation.get("gate"))
    if gate_ok is False:
        return True, "morning gate failed"

    snapshot = payload.get("snapshot") or {}
    quote_fetch = snapshot.get("quote_fetch") or {}
    cov = quote_fetch.get("coverage_pct")
    if cov is not None and float(cov) <= 0:
        errors = quote_fetch.get("errors") or {}
        hint = f" ({len(errors)} quote errors)" if errors else ""
        return True, f"quote_fetch coverage 0%{hint}"

    harness = payload.get("harness_summary") or {}
    for item in harness.get("refinements") or []:
        signals = item.get("verification_signals") or (
            (item.get("apply_gate") or {}).get("verification_signals")
        )
        if not signals:
            continue
        for sig in signals:
            if sig in ("morning_audit_failed", "morning_gate_failed"):
                return True, f"harness signal: {sig}"

    return False, "morning manifest ok"


def needs_morning_catchup(
    *,
    now: Optional[datetime] = None,
    settings: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    from agent_reach.daily_run.settings import load_settings
    from agent_reach.daily_run.trade_calendar import is_trading_day

    sh_now = now or datetime.now(_SH_TZ)
    if sh_now.tzinfo is None:
        sh_now = sh_now.replace(tzinfo=_SH_TZ)
    else:
        sh_now = sh_now.astimezone(_SH_TZ)

    if sh_now.hour != 8 or sh_now.minute < 5:
        return False, f"outside catchup window ({sh_now.strftime('%H:%M')} Shanghai)"

    cfg = settings or load_settings()
    if not _morning_catchup_cfg(cfg)["enabled"]:
        return False, "morning_catchup disabled in settings"

    trading_ok, trading_reason = is_trading_day(settings=cfg)
    if not trading_ok:
        return False, trading_reason

    if has_morning_catchup_today():
        return False, "morning catchup already ran today"

    need, detail = morning_manifest_needs_catchup(primary_morning_manifest_today())
    if not need:
        return False, detail
    return True, detail


def run_morning_catchup(*, push: Optional[bool] = None, config=None) -> dict[str, Any]:
    from agent_reach.daily_run.schedule import run_scheduled
    from agent_reach.daily_run.settings import load_settings

    settings = load_settings()
    should_run, reason = needs_morning_catchup(settings=settings)
    if not should_run:
        return {"catchup": False, "reason": reason}

    cfg = _morning_catchup_cfg(settings)
    do_push = cfg["push"] if push is None else push
    os.environ[MORNING_CATCHUP_ENV] = "1"
    try:
        result = run_scheduled("morning", push=do_push, config=config, force=True)
    finally:
        os.environ.pop(MORNING_CATCHUP_ENV, None)

    return {
        "catchup": True,
        "reason": reason,
        "push": do_push,
        "result": result,
    }


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="08:05 one-shot morning catchup (L1-B)")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Run morning with Feishu push disabled",
    )
    parser.add_argument("--json", action="store_true", help="JSON output on stdout")
    args = parser.parse_args()

    try:
        from loguru import logger
    except ImportError:
        import logging

        logger = logging.getLogger("agent_reach.daily_run.morning_catchup")

    out = run_morning_catchup(push=False if args.no_push else None)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    elif out.get("catchup"):
        logger.info("morning catchup ran: {}", out.get("reason"))
    else:
        logger.info("morning catchup skipped: {}", out.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())