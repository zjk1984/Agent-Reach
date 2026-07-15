# -*- coding: utf-8
"""Run morning / close / intraday once per portfolio symbol."""

from __future__ import annotations

import time
from typing import Any, Optional

from agent_reach.daily_run.settings import load_settings
from agent_reach.daily_run.snapshot_builder import build_and_save, load_portfolio
from agent_reach.daily_run.symbols import resolve_target_symbols, symbol_display_name


def symbol_push_interval(settings: dict[str, Any]) -> float:
    sched = settings.get("schedule") or {}
    report = settings.get("report") or {}
    return float(
        sched.get("symbol_push_interval_seconds")
        or report.get("split_push_interval_seconds")
        or 0.3
    )


def run_morning_for_symbols(
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    config=None,
    doctor_channels: Optional[dict[str, dict]] = None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.workflows import run_morning, save_morning_baseline

    cfg = settings or load_settings()
    pf = load_portfolio()
    targets = symbols or resolve_target_symbols(pf, cfg)
    primary = pf.get("primary_code")
    interval = symbol_push_interval(cfg)
    symbol_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, code in enumerate(targets):
        if i > 0 and push:
            time.sleep(interval)
        try:
            snap, path = build_and_save(
                report_type="premarket",
                config=config,
                primary_code=code,
                portfolio=pf,
            )
            run_result = run_morning(
                snap,
                settings=cfg,
                doctor_channels=doctor_channels,
                push=push,
                start_notify=push and i == 0,
                config=config,
            )
            baseline_path = save_morning_baseline(
                run_result["snapshot"],
                code=code,
                primary_code=primary,
            )
            symbol_results.append(
                {
                    "code": code,
                    "name": symbol_display_name(pf, code),
                    "snapshot_path": str(path),
                    "baseline_path": str(baseline_path),
                    "result": run_result,
                    "feishu": run_result.get("feishu"),
                }
            )
        except Exception as exc:
            errors.append(f"{code}: {exc}")

    if errors and not symbol_results:
        raise RuntimeError(errors[0])

    return {
        "job": "morning",
        "symbols_mode": (cfg.get("schedule") or {}).get("symbols_mode", "primary"),
        "symbols": targets,
        "symbol_results": symbol_results,
        "errors": errors,
        "feishu": symbol_results[-1]["feishu"] if symbol_results else None,
    }


def run_intraday_for_symbols(
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    config=None,
    doctor_channels: Optional[dict[str, dict]] = None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.intraday import (
        default_state_path,
        load_state,
        run_intraday,
        should_evaluate_trade,
    )

    cfg = settings or load_settings()
    pf = load_portfolio()
    targets = symbols or resolve_target_symbols(pf, cfg)
    interval = symbol_push_interval(cfg)
    symbol_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, code in enumerate(targets):
        if i > 0 and push:
            time.sleep(interval)
        state_path = default_state_path(code)
        state = load_state(state_path)
        if len(state.scans) >= 10:
            symbol_results.append(
                {"code": code, "skipped": True, "reason": "今日扫描已达 10 次上限"}
            )
            continue
        try:
            snap, path = build_and_save(
                report_type="intraday",
                config=config,
                primary_code=code,
                portfolio=pf,
            )
            do_trade = should_evaluate_trade(state, cfg, state_path=state_path)
            run_result = run_intraday(
                snap,
                settings=cfg,
                doctor_channels=doctor_channels,
                push=push,
                trade=do_trade,
                config=config,
                state_path=state_path,
            )
            symbol_results.append(
                {
                    "code": code,
                    "name": symbol_display_name(pf, code),
                    "snapshot_path": str(path),
                    "trade_evaluated": do_trade,
                    "result": run_result,
                    "feishu": run_result.get("feishu"),
                }
            )
        except Exception as exc:
            errors.append(f"{code}: {exc}")

    if errors and not symbol_results:
        raise RuntimeError(errors[0])

    return {
        "job": "intraday",
        "symbols": targets,
        "symbol_results": symbol_results,
        "errors": errors,
        "feishu": next((r.get("feishu") for r in reversed(symbol_results) if r.get("feishu")), None),
    }


def run_close_for_symbols(
    *,
    settings: Optional[dict[str, Any]] = None,
    push: bool = True,
    config=None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.intraday import load_state
    from agent_reach.daily_run.workflows import load_morning_baseline, run_close

    cfg = settings or load_settings()
    pf = load_portfolio()
    targets = symbols or resolve_target_symbols(pf, cfg)
    interval = symbol_push_interval(cfg)
    symbol_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, code in enumerate(targets):
        if i > 0 and push:
            time.sleep(interval)
        try:
            baseline = load_morning_baseline(code=code)
            snap, path = build_and_save(
                report_type="close",
                config=config,
                primary_code=code,
                portfolio=pf,
            )
            state = load_state(code=code)
            if state.scans:
                snap["intraday_scans"] = state.scans
                snap["mss_intraday_actual"] = [s.get("mss_final") for s in state.scans]

            run_result = run_close(
                snap,
                baseline,
                settings=cfg,
                push=push,
                config=config,
            )
            symbol_results.append(
                {
                    "code": code,
                    "name": symbol_display_name(pf, code),
                    "snapshot_path": str(path),
                    "result": run_result,
                    "feishu": run_result.get("feishu"),
                }
            )
        except Exception as exc:
            errors.append(f"{code}: {exc}")

    if errors and not symbol_results:
        raise RuntimeError(errors[0])

    return {
        "job": "close",
        "symbols": targets,
        "symbol_results": symbol_results,
        "errors": errors,
        "feishu": symbol_results[-1]["feishu"] if symbol_results else None,
    }
