# -*- coding: utf-8
"""Optuna/grid hyperopt-lite for deploy_ratio + sector_gap + macro_veto (Freqtrade-inspired)."""

from __future__ import annotations

import itertools
from typing import Any, Optional

HYPEROPT_LITE_BOUNDS: dict[str, tuple[float, float, int]] = {
    "deploy_ratio": (0.15, 0.35, 5),
    "sector_gap_min_fade_pct": (1.5, 3.0, 4),
    "sector_gap_macro_veto_bump": (2.0, 5.0, 4),
}


def hyperopt_lite_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("hyperopt_lite") or {})
    return {
        "enabled": block.get("enabled", True) is not False,
        "trials": max(8, int(block.get("trials", 24))),
        "prefer_optuna": block.get("prefer_optuna", True) is not False,
    }


def _grid_values(name: str) -> list[float]:
    lo, hi, steps = HYPEROPT_LITE_BOUNDS[name]
    if steps <= 1:
        return [float(lo)]
    step = (hi - lo) / (steps - 1)
    return [round(lo + step * i, 4) for i in range(steps)]


def _loss(params: dict[str, float], report: dict[str, Any]) -> float:
    whatif = report.get("sell_rules_whatif") or {}
    baseline = float(whatif.get("baseline_realized_pnl") or whatif.get("baseline_pnl") or 0)
    evolved = float(whatif.get("evolved_realized_pnl") or whatif.get("evolved_pnl") or 0)
    weekly_pct = float(report.get("weekly_pnl_pct") or 0)

    deploy = float(params["deploy_ratio"])
    fade = float(params["sector_gap_min_fade_pct"])
    bump = float(params["sector_gap_macro_veto_bump"])

    if baseline > evolved:
        deploy_target = 0.20
    elif baseline < evolved:
        deploy_target = 0.30
    else:
        deploy_target = 0.25

    loss = abs(deploy - deploy_target) * 10.0
    loss += max(0.0, -weekly_pct) * 2.0
    loss += abs(baseline - evolved) / max(1.0, abs(baseline) + abs(evolved) + 1.0)
    if weekly_pct < -1.0:
        loss += (fade - 2.0) ** 2 * 0.5
        loss += max(0.0, 4.0 - bump) * 0.3
    return round(loss, 6)


def _search_grid(report: dict[str, Any], *, trials: int) -> dict[str, Any]:
    keys = list(HYPEROPT_LITE_BOUNDS)
    combos = list(
        itertools.product(*(_grid_values(k) for k in keys))
    )
    if len(combos) > trials:
        step = max(1, len(combos) // trials)
        combos = combos[::step][:trials]

    best_loss = None
    best_params: dict[str, float] = {}
    for combo in combos:
        params = dict(zip(keys, combo))
        loss = _loss(params, report)
        if best_loss is None or loss < best_loss:
            best_loss = loss
            best_params = params
    return {
        "planner": "grid",
        "loss": best_loss,
        "params": best_params,
        "trials": len(combos),
    }


def _search_optuna(report: dict[str, Any], *, trials: int) -> Optional[dict[str, Any]]:
    try:
        import optuna
    except ImportError:
        return None

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        params = {
            "deploy_ratio": trial.suggest_float(
                "deploy_ratio", *HYPEROPT_LITE_BOUNDS["deploy_ratio"][:2]
            ),
            "sector_gap_min_fade_pct": trial.suggest_float(
                "sector_gap_min_fade_pct", *HYPEROPT_LITE_BOUNDS["sector_gap_min_fade_pct"][:2]
            ),
            "sector_gap_macro_veto_bump": trial.suggest_float(
                "sector_gap_macro_veto_bump", *HYPEROPT_LITE_BOUNDS["sector_gap_macro_veto_bump"][:2]
            ),
        }
        return _loss(params, report)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    return {
        "planner": "optuna",
        "loss": float(study.best_value),
        "params": dict(study.best_params),
        "trials": trials,
    }


def run_hyperopt_lite(
    report: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = hyperopt_lite_cfg(settings)
    if not cfg["enabled"]:
        return {"skipped": True, "reason": "hyperopt_lite disabled", "job": "hyperopt_lite"}

    trials = int(cfg["trials"])
    result: dict[str, Any]
    if cfg["prefer_optuna"]:
        result = _search_optuna(report, trials=trials) or _search_grid(report, trials=trials)
    else:
        result = _search_grid(report, trials=trials)

    params = result.get("params") or {}
    return {
        "skipped": False,
        "job": "hyperopt_lite",
        "planner": result.get("planner"),
        "loss": result.get("loss"),
        "trials": result.get("trials"),
        "optimal": params,
        "message": (
            f"hyperopt-lite {result.get('planner')} loss={result.get('loss'):.4f} "
            f"deploy={params.get('deploy_ratio', 0):.0%} "
            f"fade={params.get('sector_gap_min_fade_pct')} "
            f"bump={params.get('sector_gap_macro_veto_bump')}"
        ),
    }


def hyperopt_lite_to_harness_evidence(
    result: dict[str, Any],
    *,
    report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if result.get("skipped"):
        return {"summary": "hyperopt_lite skipped", "memory": [], "policy": [], "playbook": [], "plan": []}

    params = dict(result.get("optimal") or {})
    memory = [str(result.get("message") or "hyperopt-lite completed")]
    policy = [
        (
            "hyperopt-lite deploy_ratio="
            f"{float(params.get('deploy_ratio', 0.25)):.2f} "
            f"sector_gap_min_fade_pct={float(params.get('sector_gap_min_fade_pct', 2.0)):.2f} "
            f"macro_veto_bump={float(params.get('sector_gap_macro_veto_bump', 3.0)):.2f}"
        )
    ]
    playbook = [
        "hyperopt-lite：基准/自进化 what-if 更优侧对齐 deploy_ratio 与 sector_gap_guard"
    ]
    plan: list[str] = []
    if report:
        week = f"{report.get('week_start')}~{report.get('week_end')}"
        plan.append(f"weekly {week}：验证 hyperopt-lite 三参数是否改善 realized 差")
    return {
        "summary": result.get("message") or "hyperopt_lite",
        "memory": memory,
        "policy": policy,
        "playbook": playbook,
        "plan": plan,
        "rigor_domain": {"hyperopt_lite": result, "report_week": report.get("week_start") if report else None},
    }
