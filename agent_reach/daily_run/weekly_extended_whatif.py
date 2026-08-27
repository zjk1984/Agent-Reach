# -*- coding: utf-8
"""Weekly extended what-if blocks for forecast / optimizer grid / Kronos replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


def _kronos_in_text(text: str) -> bool:
    return "kronos" in str(text or "").lower()


@dataclass
class WeeklyExtendedWhatIfResult:
    skipped: bool = False
    skip_reason: str = ""
    scope: str = "weekly"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "scope": self.scope,
        }
        for key, value in self.__dict__.items():
            if key in out or key.startswith("_"):
                continue
            out[key] = value
        return out


@dataclass
class ForecastCalibrateWhatIfResult(WeeklyExtendedWhatIfResult):
    week_start: str = ""
    week_end: str = ""
    divergence_symbol_days: int = 0
    divergence_symbols: int = 0
    calibration_used: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizerWhatIfResult(WeeklyExtendedWhatIfResult):
    objective: str = ""
    trials: int = 0
    current_params: dict[str, Any] = field(default_factory=dict)
    current_score: float = 0.0
    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    score_delta: float = 0.0
    runtime_underperforms: bool = False


@dataclass
class KronosWhatIfResult(WeeklyExtendedWhatIfResult):
    kronos_blocked_signals: int = 0
    kronos_relaxed_buys: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)


def _optimizer_history_from_week(
    mss_summary: list[dict[str, Any]],
    daily_totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build MSS backtest rows from weekly trajectory + close totals."""
    close_totals: dict[str, float] = {}
    for row in daily_totals or []:
        if str(row.get("job") or "") != "close":
            continue
        ds = str(row.get("date") or "")[:10]
        if not ds:
            continue
        try:
            close_totals[ds] = float(row.get("total") or 0)
        except (TypeError, ValueError):
            continue

    mss_by_date: dict[str, float] = {}
    for row in mss_summary or []:
        ds = str(row.get("date") or "")[:10]
        if not ds:
            continue
        if str(row.get("job") or "") not in ("close", "intraday", "morning"):
            continue
        try:
            mss_by_date[ds] = float(row.get("mss_final") or row.get("mss") or 0)
        except (TypeError, ValueError):
            continue

    dates = sorted(mss_by_date.keys())
    history: list[dict[str, Any]] = []
    prev_total: Optional[float] = None
    price = 100.0
    for ds in dates:
        mss = mss_by_date.get(ds)
        if mss is None:
            continue
        daily_ret = 0.0
        total = close_totals.get(ds)
        if prev_total is not None and total is not None and prev_total > 0:
            daily_ret = (total - prev_total) / prev_total
        if daily_ret:
            price = max(price * (1 + daily_ret), 0.01)
        history.append(
            {
                "date": ds,
                "mss_final": mss,
                "return": round(daily_ret, 6),
                "price": round(price, 4),
            }
        )
        if total is not None:
            prev_total = total
    return history


def build_weekly_forecast_calibrate_whatif(
    *,
    week_start: date,
    week_end: date,
    settings: Optional[dict[str, Any]] = None,
) -> ForecastCalibrateWhatIfResult:
    from agent_reach.daily_run.week_forecast import load_forecast

    forecast = load_forecast(week_start)
    if not forecast:
        return ForecastCalibrateWhatIfResult(
            skipped=True,
            skip_reason="本周无 persisted week_forecast，跳过 forecast what-if",
        )

    div_days = 0
    div_symbols = 0
    for sym in (forecast.get("symbols") or {}).values():
        days = sym.get("kronos_divergence_days") or []
        if not days:
            continue
        div_symbols += 1
        div_days += len(days)

    if div_days <= 0:
        return ForecastCalibrateWhatIfResult(
            skipped=True,
            skip_reason="本周 forecast 无 Kronos/MSS 分歧日",
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            calibration_used=dict(forecast.get("calibration_used") or {}),
        )

    return ForecastCalibrateWhatIfResult(
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        divergence_symbol_days=div_days,
        divergence_symbols=div_symbols,
        calibration_used=dict(forecast.get("calibration_used") or {}),
    )


def build_weekly_optimizer_whatif(
    *,
    week_start: date,
    week_end: date,
    mss_summary: list[dict[str, Any]],
    daily_totals: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
) -> OptimizerWhatIfResult:
    from agent_reach.daily_run.backtest import run_mss_backtest
    from agent_reach.daily_run.harness_policy import aggressive_entry_default, macro_veto_default
    from agent_reach.daily_run.optimizer import grid_search_optimize, resolve_optimize_objective
    from agent_reach.daily_run.settings import load_settings

    cfg = settings or load_settings()
    opt_cfg = dict(cfg.get("optimizer") or {})
    if opt_cfg.get("harness_evolve") is False:
        return OptimizerWhatIfResult(
            skipped=True,
            skip_reason="optimizer.harness_evolve disabled",
        )

    history = _optimizer_history_from_week(mss_summary, daily_totals)
    if len(history) < 2:
        return OptimizerWhatIfResult(
            skipped=True,
            skip_reason="本周 MSS/净值样本不足，跳过 grid what-if",
        )

    objective = resolve_optimize_objective(settings=cfg)
    try:
        best = grid_search_optimize(history, cfg, objective=objective)
    except ValueError as exc:
        return OptimizerWhatIfResult(skipped=True, skip_reason=str(exc))

    backtest_cfg = cfg.get("backtest") or {}
    current_veto = float(macro_veto_default(cfg))
    current_entry = float(aggressive_entry_default(cfg))
    current_bt = run_mss_backtest(
        history,
        macro_veto=current_veto,
        aggressive_entry=current_entry,
        initial_capital=float(backtest_cfg.get("default_initial_capital", 100_000)),
        commission_rate=float(backtest_cfg.get("commission_rate", 0.0015)),
    )
    from agent_reach.daily_run.optimizer import _objective_fn

    score_fn = _objective_fn(objective)
    current_score = float(score_fn(current_bt))
    best_score = float(best.best_score)
    score_delta = round(best_score - current_score, 6)
    min_delta = float(
        dict((cfg.get("rejected_strategies") or {}).get("weekly_whatif") or {}).get(
            "optimizer_score_delta_min", 0.05
        )
    )

    return OptimizerWhatIfResult(
        objective=objective,
        trials=int(best.trials),
        current_params={"macro_veto": current_veto, "aggressive_entry": current_entry},
        current_score=round(current_score, 6),
        best_params=dict(best.best_params),
        best_score=round(best_score, 6),
        score_delta=score_delta,
        runtime_underperforms=score_delta >= min_delta,
    )


def build_weekly_kronos_whatif(
    *,
    week_start: date,
    week_end: date,
    manifests: list[dict[str, Any]],
    buy_rules_whatif: Optional[dict[str, Any]] = None,
    intraday_friction_whatif: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> KronosWhatIfResult:
    from agent_reach.daily_run.sell_rules_whatif import _intraday_trades_for_day

    cfg = settings or {}
    blocked = 0
    relaxed = 0
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _note(code: str, name: str, source: str, reason: str) -> None:
        nonlocal blocked, relaxed
        key = f"{code}|{source}|{reason[:40]}"
        if key in seen:
            return
        seen.add(key)
        rows.append({"code": code, "name": name, "source": source, "reason": reason[:120]})
        if "偏强" in reason or "relax" in reason.lower():
            relaxed += 1
        else:
            blocked += 1

    buy = buy_rules_whatif or {}
    if not buy.get("skipped"):
        for row in buy.get("rows") or []:
            reason = str(row.get("block_reason") or "")
            if not _kronos_in_text(reason):
                continue
            code = str(row.get("code") or "")
            name = str(row.get("name") or code)
            _note(code, name, "buy_whatif", reason)

    friction = intraday_friction_whatif or {}
    if not friction.get("skipped"):
        for row in friction.get("rows") or []:
            reason = str(row.get("block_reason") or "")
            if not _kronos_in_text(reason):
                continue
            code = str(row.get("code") or "")
            name = str(row.get("name") or code)
            _note(code, name, "intraday_friction_whatif", reason)

    manifests_by_day: dict[str, list[dict[str, Any]]] = {}
    for record in manifests or []:
        day = str(record.get("_run_date") or "")[:10]
        if day:
            manifests_by_day.setdefault(day, []).append(record)

    for day, day_manifests in sorted(manifests_by_day.items()):
        try:
            day_date = date.fromisoformat(day)
        except ValueError:
            continue
        if not (week_start <= day_date <= week_end):
            continue
        for entry in _intraday_trades_for_day(day, settings=cfg, day_manifests=day_manifests):
            reason = str(entry.get("reasoning") or entry.get("block_reason") or "")
            if not _kronos_in_text(reason):
                continue
            if str(entry.get("action") or "hold") == "buy":
                continue
            code = str(entry.get("code") or "")
            name = str(entry.get("name") or code)
            _note(code, name, "intraday_manifest", reason)

    if blocked <= 0 and relaxed <= 0:
        return KronosWhatIfResult(
            skipped=True,
            skip_reason="本周无 Kronos 买入阻断/放宽信号",
        )

    return KronosWhatIfResult(
        kronos_blocked_signals=blocked,
        kronos_relaxed_buys=relaxed,
        rows=rows[:12],
    )
