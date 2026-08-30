# -*- coding: utf-8
"""Sunday forecast advanced insights — scatter history, model consistency, stress tests."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import today_shanghai
from agent_reach.daily_run.week_forecast import load_forecast, next_trading_week_range

_TRIGGER_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元")


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: float, *, signed: bool = True) -> str:
    if signed:
        return f"{value:+.1f}%"
    return f"{value:.1f}%"


def _prior_week_start(week_start: date) -> date:
    return week_start - timedelta(days=7)


def _direction_label(mid: Optional[float]) -> str:
    if mid is None:
        return "中性"
    if mid > 0.3:
        return "看多"
    if mid < -0.3:
        return "看空"
    return "中性"


def _consistency_tier(bullish: int, bearish: int, total: int) -> str:
    if total <= 1:
        return "单模型"
    aligned = max(bullish, bearish)
    if aligned >= total:
        return "高"
    if aligned >= total - 1 and total >= 3:
        return "中等"
    return "低"


def build_market_prediction_scatter(
    *,
    as_of: Optional[date] = None,
    weeks: int = 4,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Text scatter: predicted midpoint vs realized benchmark return."""
    d = as_of or today_shanghai()
    week_start, _ = next_trading_week_range(d)
    cursor = week_start
    points: list[dict[str, Any]] = []

    for _ in range(min(max(int(weeks), 4), 8)):
        prior_start = _prior_week_start(cursor)
        fc = load_forecast(prior_start)
        cursor = prior_start
        if not fc:
            continue

        structured = fc.get("structured_predictions") or {}
        market = structured.get("market") or {}
        pred_mid = _optional_float(market.get("change_pct_mid"))
        if pred_mid is None:
            lo = _optional_float(market.get("change_pct_low"))
            hi = _optional_float(market.get("change_pct_high"))
            if lo is not None and hi is not None:
                pred_mid = (lo + hi) / 2

        ws = date.fromisoformat(str(fc.get("week_start")))
        we = date.fromisoformat(str(fc.get("week_end")))
        actual: Optional[float] = None
        verification = fc.get("week_verification") or {}
        for row in verification.get("rows") or []:
            pred_s = str(row.get("prediction") or "")
            if "大盘" in pred_s or "沪深300" in pred_s:
                act_s = str(row.get("actual") or "")
                if act_s.endswith("%"):
                    try:
                        actual = float(act_s.rstrip("%").replace("+", ""))
                    except ValueError:
                        pass
                break
        if actual is None:
            from agent_reach.daily_run.weekly_card_metrics import fetch_benchmark_weekly_return

            bench = fetch_benchmark_weekly_return(ws, we, settings=settings)
            actual = _optional_float(bench.get("return_pct"))

        if pred_mid is None or actual is None:
            continue

        dev = round(actual - pred_mid, 2)
        dir_hit = (pred_mid > 0.3 and actual > 0.3) or (pred_mid < -0.3 and actual < -0.3) or (
            abs(pred_mid) <= 0.3 and abs(actual) <= 1.0
        )
        index_name = market.get("index_name") or "沪深300"
        points.append(
            {
                "week_start": fc.get("week_start"),
                "week_end": fc.get("week_end"),
                "index_name": index_name,
                "predicted_mid_pct": round(pred_mid, 2),
                "actual_pct": round(actual, 2),
                "deviation_pct": dev,
                "direction_hit": dir_hit,
            }
        )

    points.reverse()
    if not points:
        return {"points": [], "weeks": 0}

    devs = [abs(float(p["deviation_pct"])) for p in points]
    dir_hits = sum(1 for p in points if p.get("direction_hit"))
    return {
        "index_name": points[-1].get("index_name") or "沪深300",
        "points": points,
        "weeks": len(points),
        "avg_abs_deviation_pct": round(sum(devs) / len(devs), 2),
        "direction_accuracy_pct": round(dir_hits / len(points) * 100.0, 1),
        "direction_hits": dir_hits,
        "direction_total": len(points),
        "bias_pct": round(sum(float(p["deviation_pct"]) for p in points) / len(points), 2),
    }


def _model_votes_for_symbol(
    *,
    code: str,
    sym: dict[str, Any],
    forecast: dict[str, Any],
    enriched: Optional[dict[str, Any]] = None,
) -> list[tuple[str, str]]:
    votes: list[tuple[str, str]] = []
    days = sym.get("days") or {}
    if days:
        cum = sum(_optional_float(d.get("expected_change_pct")) or 0.0 for d in days.values())
        votes.append(("路径", _direction_label(cum)))

    kronos = (forecast.get("kronos_paths") or {}).get(code) or sym.get("kronos") or {}
    if kronos.get("available"):
        cum_k = _optional_float(kronos.get("cum_change_pct"))
        votes.append(("Kronos", _direction_label(cum_k)))

    row = enriched or {}
    mss = _optional_float(row.get("mss_final"))
    if mss is not None:
        if mss >= 55:
            votes.append(("资金面", "看多"))
        elif mss <= 45:
            votes.append(("资金面", "看空"))
        else:
            votes.append(("资金面", "中性"))

    price = _optional_float(row.get("price") or sym.get("base_price"))
    ma20 = _optional_float(row.get("ma20"))
    if price is not None and ma20 is not None:
        votes.append(("技术面", "看多" if price >= ma20 else "看空"))

    return votes


def build_model_consistency(
    *,
    forecast: dict[str, Any],
    structured: Optional[dict[str, Any]] = None,
    enriched_map: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    structured = structured or forecast.get("structured_predictions") or {}
    symbols = structured.get("symbols") or []
    rows: list[dict[str, Any]] = []

    for pred in symbols:
        code = _normalize_code(str(pred.get("code") or ""))
        if not code:
            continue
        sym = (forecast.get("symbols") or {}).get(code) or {}
        votes = _model_votes_for_symbol(
            code=code,
            sym=sym,
            forecast=forecast,
            enriched=(enriched_map or {}).get(code),
        )
        if not votes:
            continue
        bullish = sum(1 for _, v in votes if v == "看多")
        bearish = sum(1 for _, v in votes if v == "看空")
        neutral = len(votes) - bullish - bearish
        tier = _consistency_tier(bullish, bearish, len(votes))
        base_conf = _optional_float(pred.get("confidence_pct")) or 60.0
        if tier == "高":
            adj_conf = min(92.0, base_conf + 5)
        elif tier == "低":
            adj_conf = max(35.0, base_conf - 10)
        else:
            adj_conf = base_conf
        dominant = "看多" if bullish > bearish else "看空" if bearish > bullish else "中性"
        name = str(pred.get("name") or code)
        vote_s = "、".join(f"{label}{view}" for label, view in votes)
        rows.append(
            {
                "code": code,
                "name": name,
                "model_count": len(votes),
                "bullish": bullish,
                "bearish": bearish,
                "neutral": neutral,
                "dominant": dominant,
                "consistency": tier,
                "confidence_pct": round(adj_conf, 0),
                "base_confidence_pct": round(base_conf, 0),
                "summary": (
                    f"{name}预测：{len(votes)}个模型中{bullish}个看多、{bearish}个看空"
                    f"{f'、{neutral}个中性' if neutral else ''}，一致性{tier}，置信度{adj_conf:.0f}%"
                ),
                "votes": vote_s,
            }
        )
    return rows


def build_stress_tests(
    *,
    portfolio: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    matrix: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    pf = portfolio or {}
    total = _optional_float(pf.get("total_value") or pf.get("portfolio_total"))
    stock_w = 0.0
    if total:
        stock_w = sum(
            float(h.get("market_value") or 0) / float(total) * 100.0 for h in pf.get("holdings") or []
        )
    else:
        stock_w = 60.0
    guidance = (matrix or {}).get("position_guidance") or {}
    cash_w = _optional_float(guidance.get("current_cash_pct"))
    if cash_w is None:
        cash_w = max(0.0, 100.0 - stock_w)

    beta = 1.15
    crash = -5.0
    port_loss = round(stock_w / 100.0 * crash * beta, 2)
    max_dd = round(abs(port_loss) * 1.35 + max(0.0, (100 - cash_w) / 100 * 0.5), 2)
    cushion = "可抵御" if cash_w >= 35 else "需降仓"

    tests: list[dict[str, Any]] = [
        {
            "scenario": "大盘暴跌5%",
            "text": (
                f"压力测试：若大盘暴跌5%，组合预计亏损{abs(port_loss):.1f}%，"
                f"最大回撤{max_dd:.1f}%，现金比例{cash_w:.0f}%{cushion}"
            ),
        }
    ]

    if pf.get("holdings"):
        top = max(pf["holdings"], key=lambda h: float(h.get("market_value") or 0))
        top_w = float(top.get("market_value") or 0) / float(total) * 100.0 if total else 15.0
        name = str(top.get("name") or top.get("code"))
        shock = round(top_w / 100.0 * -10.0, 2)
        total_shock = round(port_loss + shock * 0.6, 2)
        tests.append(
            {
                "scenario": f"{name}财报暴雷-10%",
                "text": (
                    f"压力测试：若{name}单周-10%（仓位{top_w:.0f}%），"
                    f"组合额外拖累约{abs(shock):.1f}%，合计约{total_shock:.1f}%"
                ),
            }
        )
    return tests


def _parse_trigger_price(trigger: str) -> Optional[float]:
    m = _TRIGGER_PRICE_RE.search(str(trigger or ""))
    if not m:
        return None
    return _optional_float(m.group(1))


def _week_low_for_symbol(code: str, prior_forecast: dict[str, Any]) -> Optional[float]:
    structured = prior_forecast.get("structured_predictions") or {}
    for pred in structured.get("symbols") or []:
        if _normalize_code(str(pred.get("code") or "")) != _normalize_code(code):
            continue
        from agent_reach.daily_run.forecast_structured import _symbol_week_actuals

        _, low_p, _ = _symbol_week_actuals(pred, prior_forecast)
        return low_p
    return None


def _week_change_for_symbol(code: str, prior_forecast: dict[str, Any]) -> Optional[float]:
    structured = prior_forecast.get("structured_predictions") or {}
    for pred in structured.get("symbols") or []:
        if _normalize_code(str(pred.get("code") or "")) != _normalize_code(code):
            continue
        from agent_reach.daily_run.forecast_structured import _symbol_week_actuals

        _, _, chg = _symbol_week_actuals(pred, prior_forecast)
        return chg
    return None


def build_prior_operation_execution(
    prior_forecast: Optional[dict[str, Any]],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not prior_forecast:
        return {}
    matrix = prior_forecast.get("operation_matrix") or {}
    rows = matrix.get("master_rows") or []
    if not rows:
        return {}

    from agent_reach.daily_run.forecast_tracking import compute_operation_return_vs_hold

    op_returns = compute_operation_return_vs_hold(prior_forecast, settings=settings)
    lines: list[str] = []

    for row in rows:
        code = str(row.get("code") or "")
        if code == "CASH":
            continue
        op = str(row.get("operation") or "")
        if op in ("—", "持有") and not row.get("trigger"):
            continue
        name = str(row.get("name") or code)
        trigger = str(row.get("trigger") or "—")
        trigger_px = _parse_trigger_price(trigger)
        week_low = _week_low_for_symbol(code, prior_forecast)
        week_chg = _week_change_for_symbol(code, prior_forecast)

        executable = "—"
        if op in ("加仓", "新建仓") and trigger_px is not None:
            if week_low is not None:
                executable = "可执行" if week_low <= trigger_px * 1.03 else f"未触发（最低{week_low:.0f}元）"
            else:
                executable = "待验证"
        elif op == "减仓" and trigger_px is not None:
            executable = "可执行" if week_low is not None else "待验证"

        detail_parts = [f"建议{name}{trigger}{op}"]
        if week_low is not None and trigger_px is not None and op in ("加仓", "新建仓"):
            detail_parts.append(f"实际最低{week_low:.0f}元，{executable}")
        elif executable != "—":
            detail_parts.append(executable)
        if week_chg is not None:
            detail_parts.append(f"本周涨跌{_fmt_pct(week_chg)}")
        lines.append(
            {
                "name": name,
                "operation": op,
                "trigger": trigger,
                "executable": executable,
                "week_change_pct": week_chg,
                "text": "，".join(detail_parts),
            }
        )

    hold_ret = op_returns.get("hold_return_pct")
    plan_ret = op_returns.get("plan_return_pct")
    summary = ""
    if hold_ret is not None and plan_ret is not None:
        summary = (
            f"按建议操作后本周收益{_fmt_pct(float(plan_ret))}，"
            f"优于持有不动的{_fmt_pct(float(hold_ret))}"
            if float(plan_ret) > float(hold_ret)
            else f"按建议操作后本周收益{_fmt_pct(float(plan_ret))}，"
            f"持有不动{_fmt_pct(float(hold_ret))}"
        )

    return {
        "lines": lines[:6],
        "operation_returns": op_returns,
        "summary": summary,
        "week_start": prior_forecast.get("week_start"),
        "week_end": prior_forecast.get("week_end"),
    }


def build_forecast_advanced_insights(
    *,
    forecast: dict[str, Any],
    prior_forecast: Optional[dict[str, Any]] = None,
    portfolio: Optional[dict[str, Any]] = None,
    structured: Optional[dict[str, Any]] = None,
    matrix: Optional[dict[str, Any]] = None,
    enriched_map: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ws = forecast.get("week_start")
    try:
        as_of = date.fromisoformat(str(ws)) if ws else today_shanghai()
    except ValueError:
        as_of = today_shanghai()

    return {
        "scatter": build_market_prediction_scatter(as_of=as_of, weeks=4, settings=settings),
        "model_consistency": build_model_consistency(
            forecast=forecast,
            structured=structured,
            enriched_map=enriched_map,
        ),
        "stress_tests": build_stress_tests(
            portfolio=portfolio,
            structured=structured,
            matrix=matrix,
        ),
        "prior_operation_execution": build_prior_operation_execution(
            prior_forecast,
            settings=settings,
        ),
    }


def render_scatter_history_markdown(scatter: dict[str, Any]) -> str:
    points = scatter.get("points") or []
    if not points:
        return ""
    index_name = scatter.get("index_name") or "沪深300"
    lines = [
        f"**过去{len(points)}周{index_name}预测 vs 实际：**",
        "```",
    ]
    for idx, pt in enumerate(points, start=1):
        dev = float(pt.get("deviation_pct") or 0)
        lines.append(
            f"第{idx}周：预测{_fmt_pct(float(pt['predicted_mid_pct']))} → "
            f"实际{_fmt_pct(float(pt['actual_pct']))}（偏差{_fmt_pct(dev)}）"
        )
    avg_dev = scatter.get("avg_abs_deviation_pct")
    dir_hits = scatter.get("direction_hits")
    dir_total = scatter.get("direction_total")
    bias = scatter.get("bias_pct")
    if avg_dev is not None and dir_total:
        lines.append(
            f"平均偏差：{avg_dev:.1f}%，方向准确率：{dir_hits}/{dir_total}="
            f"{float(scatter.get('direction_accuracy_pct') or 0):.0f}%"
        )
    if bias is not None:
        tone = "偏乐观" if bias > 0.3 else "偏保守" if bias < -0.3 else "基本无偏"
        lines.append(f"系统性偏差：{_fmt_pct(float(bias))}（{tone}）")
    lines.append("```")
    return "\n".join(lines).strip()


def render_model_consistency_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = ["**模型一致性：**"]
    for row in rows[:5]:
        lines.append(f"- {row.get('summary')}")
    return "\n".join(lines).strip()


def render_stress_tests_markdown(tests: list[dict[str, Any]]) -> str:
    if not tests:
        return ""
    lines = ["**黑天鹅压力测试：**"]
    for item in tests[:3]:
        lines.append(f"- {item.get('text')}")
    return "\n".join(lines).strip()


def render_prior_operation_execution_markdown(block: dict[str, Any]) -> str:
    if not block or not block.get("lines"):
        return ""
    lines = ["**上周操作建议回顾：**"]
    for item in block.get("lines") or []:
        lines.append(f"- {item.get('text')}")
    summary = block.get("summary")
    if summary:
        lines.append(f"- {summary}")
    return "\n".join(lines).strip()
