#!/usr/bin/env python3
# -*- coding: utf-8
"""Run close-phase harness skills — verify-only smoke by default.

``run_close_harness_refinements()`` also accepts ``improvements``/``audit``/
``portfolio_summary``/``forecast_review``/``watchlist_adjust``/``pnl_target_cycle``
kwargs that each gate a separate harness job (close_improve, data_audit,
watchlist_intel, ...). This script only passes a stub ``verify`` dict, so by
default it exercises **verify only** — it does NOT smoke-test close_improve or
data_audit. Pass real fixtures for those kwargs (e.g. from a saved close
manifest) if you need to smoke-test the full close-phase harness cascade.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description="Close harness skills runner")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from agent_reach.daily_run.close_harness_skills import run_close_harness_refinements
    from agent_reach.daily_run.settings import effective_settings, load_settings

    cfg = effective_settings(load_settings())
    verify = {
        "name": "MARKET",
        "summary": "manual harness skill run",
        "deviations": [],
        "recommendations": [],
        "mss_within_prediction": True,
    }
    report = run_close_harness_refinements(verify=verify, settings=cfg)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
