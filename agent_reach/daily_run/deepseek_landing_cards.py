# -*- coding: utf-8
"""DeepSeek introduction scenarios and landing-point transparency cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from agent_reach.daily_run.report_push import ReportSection

_CARD_LABEL = "🤖 DeepSeek 场景·落点"
_CATEGORY = "deepseek_landing"

# Governing principle for every DeepSeek touchpoint in daily-run.
DEEPSEEK_USAGE_PRINCIPLE = (
    "计算用代码，解读用模型：价格、涨跌幅、仓位、收益率、触发条件等数字"
    "必须由量化系统确定性计算；DeepSeek 只负责把这些数字翻译成自然语言、"
    "生成解读文本、提取文本信息；禁止模型做任何影响交易决策的数值判断。"
)

DEEPSEEK_NARRATIVE_RULE = (
    "仅解读输入中已给出的数字，不得推算、修改或新增价格/涨跌幅/仓位/收益率/触发条件；"
    "不得给出新的买卖价位、目标仓位、止损位或加仓比例。"
)

_ROLE_INTERPRET = "interpret"
_ROLE_OFFLINE = "offline_research"


@dataclass(frozen=True)
class _ScenarioSpec:
    id: str
    name: str
    landing: str
    suitable_when: str
    role: str
    report_kinds: tuple[str, ...]
    is_active: Callable[[dict[str, Any], Optional[dict[str, Any]], str], bool]
    is_configured: Callable[[dict[str, Any], str], bool]


def deepseek_landing_card_enabled(settings: Optional[dict[str, Any]] = None) -> bool:
    cfg = dict((settings or {}).get("report") or {}).get("deepseek_landing_card") or {}
    if cfg.get("enabled") is False:
        return False
    return True


def _narrative_cfg(settings: dict[str, Any], job: str) -> dict[str, Any]:
    from agent_reach.daily_run.report_narrative import _narrative_cfg

    return _narrative_cfg(settings, job)


def _narrative_active(settings: dict[str, Any], runtime: Optional[dict[str, Any]], job: str) -> bool:
    narrative = dict((runtime or {}).get("narrative") or {})
    if narrative.get("planner") == "llm" and not narrative.get("skipped"):
        return True
    cfg = _narrative_cfg(settings, job)
    if str(cfg.get("planner") or "") != "llm" or cfg.get("enabled") is False:
        return False
    from agent_reach.daily_run.llm_chat import resolve_chat_provider

    provider = str(cfg.get("provider") or "auto")
    return resolve_chat_provider(provider) is not None


def _narrative_configured(settings: dict[str, Any], job: str) -> bool:
    cfg = _narrative_cfg(settings, job)
    return cfg.get("enabled") is not False


def _section_llm_optimize(settings: dict[str, Any], section: str) -> bool:
    root = dict((settings or {}).get("harness_evolution") or {})
    sec = dict((settings or {}).get(section) or {})
    if root.get("llm_optimize") is False or sec.get("llm_optimize") is False:
        return False
    return sec.get("llm_optimize", root.get("llm_optimize", True)) is not False


def _harness_block_active(runtime: Optional[dict[str, Any]], *keys: str) -> bool:
    block: Any = dict(runtime or {}).get("harness_result") or {}
    for key in keys:
        if not isinstance(block, dict):
            return False
        block = block.get(key) or {}
    if not isinstance(block, dict):
        return False
    if block.get("skipped"):
        return False
    if block.get("llm_optimal") or block.get("llm_optimize"):
        inner = block.get("llm_optimal") or block.get("llm_optimize") or block
        if isinstance(inner, dict) and inner.get("skipped"):
            return False
        if isinstance(inner, dict) and (inner.get("planner") == "deepseek" or inner.get("ratios")):
            return True
    if str(block.get("planner") or "") in ("deepseek", "llm") and (
        block.get("refinement_id") or int(block.get("changes") or 0) > 0
    ):
        return True
    return False


def _layer_b_active(settings: dict[str, Any], runtime: Optional[dict[str, Any]], _job: str) -> bool:
    harness = dict((runtime or {}).get("harness_result") or {})
    layer_b = harness.get("layer_b") or {}
    if isinstance(layer_b, dict) and str(layer_b.get("planner") or "") in ("deepseek", "llm"):
        if layer_b.get("skipped"):
            return False
        return bool(layer_b.get("refinement_id") or int(layer_b.get("changes") or 0) > 0)
    return False


def _layer_b_configured(settings: dict[str, Any], _job: str) -> bool:
    llm_refine = dict((settings or {}).get("harness") or {}).get("llm_refine") or {}
    return llm_refine.get("enabled") is not False


def _whatif_active(settings: dict[str, Any], runtime: Optional[dict[str, Any]], section: str) -> bool:
    if _harness_block_active(runtime, section):
        return True
    if _harness_block_active(runtime, "weekly_skills", section):
        return True
    if _harness_block_active(runtime, "forecast_skills", section):
        return True
    return False


def _whatif_configured(settings: dict[str, Any], section: str) -> bool:
    return _section_llm_optimize(settings, section)


def _forecast_calibrate_active(settings: dict[str, Any], runtime: Optional[dict[str, Any]], _job: str) -> bool:
    return _harness_block_active(runtime, "forecast_calibrate") or _harness_block_active(
        runtime, "forecast_skills", "forecast_calibrate"
    )


def _forecast_calibrate_configured(settings: dict[str, Any], _job: str) -> bool:
    return _section_llm_optimize(settings, "forecast_calibration")


def _weekly_threshold_active(settings: dict[str, Any], runtime: Optional[dict[str, Any]], _job: str) -> bool:
    return _harness_block_active(runtime, "weekly_threshold") or _harness_block_active(
        runtime, "weekly_skills", "weekly_threshold"
    )


def _weekly_threshold_configured(settings: dict[str, Any], _job: str) -> bool:
    return _section_llm_optimize(settings, "harness_evolution")


_SCENARIOS: tuple[_ScenarioSpec, ...] = (
    _ScenarioSpec(
        id="narrative_rules",
        name="规则解读（LLM 叙事）",
        landing="末卡「规则解读」/ AI 解读",
        suitable_when="需将 MSS/仓位/风险压缩为 3 条以内结论时",
        role=_ROLE_INTERPRET,
        report_kinds=("morning", "close", "midday", "weekly", "forecast", "intraday"),
        is_active=_narrative_active,
        is_configured=_narrative_configured,
    ),
    _ScenarioSpec(
        id="harness_layer_b",
        name="Harness Layer B 精炼",
        landing="Harness 进化卡 / harness policy 写入",
        suitable_when="多 job 参数冲突需合并提炼时（文本归纳，非实盘下单）",
        role=_ROLE_OFFLINE,
        report_kinds=("morning", "close", "weekly", "forecast"),
        is_active=_layer_b_active,
        is_configured=_layer_b_configured,
    ),
    _ScenarioSpec(
        id="sell_rules_whatif",
        name="卖出 what-if 比例寻优",
        landing="harness policy · sell_ratio / cover_ratio",
        suitable_when="收盘/周报复盘卖出 missed 样本 ≥2 时（离线研参，代码 clamp 后写入）",
        role=_ROLE_OFFLINE,
        report_kinds=("close", "weekly"),
        is_active=lambda s, r, j: _whatif_active(s, r, "sell_rules_whatif"),
        is_configured=lambda s, j: _whatif_configured(s, "sell_rules_whatif"),
    ),
    _ScenarioSpec(
        id="buy_rules_whatif",
        name="买入 what-if deploy 寻优",
        landing="harness policy · deploy_ratio / max_position",
        suitable_when="基准更优/少买 missed 样本积累时（离线研参，代码 clamp 后写入）",
        role=_ROLE_OFFLINE,
        report_kinds=("close", "weekly"),
        is_active=lambda s, r, j: _whatif_active(s, r, "buy_rules_whatif"),
        is_configured=lambda s, j: _whatif_configured(s, "buy_rules_whatif"),
    ),
    _ScenarioSpec(
        id="intraday_friction",
        name="盘中摩擦/趋势阈值寻优",
        landing="harness runtime · friction / trend_min_points",
        suitable_when="摩擦 pass 不足或趋势误判反复出现时（离线研参）",
        role=_ROLE_OFFLINE,
        report_kinds=("close", "weekly", "intraday"),
        is_active=lambda s, r, j: _whatif_active(s, r, "intraday_whatif"),
        is_configured=lambda s, j: _whatif_configured(s, "intraday_whatif"),
    ),
    _ScenarioSpec(
        id="intraday_trends",
        name="买卖趋势集合寻优",
        landing="harness runtime · buy_trends / sell_trends",
        suitable_when="趋势标签与成交结果系统性偏离时（离线研参）",
        role=_ROLE_OFFLINE,
        report_kinds=("close", "weekly", "intraday"),
        is_active=lambda s, r, j: _whatif_active(s, r, "intraday_trends"),
        is_configured=lambda s, j: _whatif_configured(s, "intraday_trends"),
    ),
    _ScenarioSpec(
        id="weekly_threshold",
        name="宏观/仓位阈值寻优",
        landing="harness runtime · macro_veto / min_cash_ratio",
        suitable_when="周六周报 threshold what-if 有显著分差时（离线研参）",
        role=_ROLE_OFFLINE,
        report_kinds=("weekly", "close"),
        is_active=_weekly_threshold_active,
        is_configured=_weekly_threshold_configured,
    ),
    _ScenarioSpec(
        id="forecast_calibrate",
        name="预测校准 spread/vol 寻优",
        landing="forecast calibration · bias/vol_scale",
        suitable_when="周日 forecast 连续偏差或 scatter 发散时（离线研参）",
        role=_ROLE_OFFLINE,
        report_kinds=("forecast", "close"),
        is_active=_forecast_calibrate_active,
        is_configured=_forecast_calibrate_configured,
    ),
    _ScenarioSpec(
        id="rejected_whatif",
        name="证伪库 weekly_whatif",
        landing="rejected_strategies policy",
        suitable_when="被否决策略反复触发同类亏损时（离线研参）",
        role=_ROLE_OFFLINE,
        report_kinds=("weekly",),
        is_active=lambda s, r, j: _whatif_active(s, r, "rejected_strategies"),
        is_configured=lambda s, j: _whatif_configured(s, "rejected_strategies"),
    ),
)


def build_deepseek_landing_snapshot(
    report_kind: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    runtime: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    settings = settings or {}
    runtime = runtime or {}
    active: list[dict[str, str]] = []
    suitable: list[dict[str, str]] = []
    for spec in _SCENARIOS:
        if report_kind not in spec.report_kinds:
            continue
        row = {
            "id": spec.id,
            "name": spec.name,
            "landing": spec.landing,
            "suitable_when": spec.suitable_when,
            "role": spec.role,
        }
        if spec.is_active(settings, runtime, report_kind):
            active.append(row)
        elif spec.is_configured(settings, report_kind):
            suitable.append(row)
    provider = ""
    model = ""
    cfg = _narrative_cfg(settings, report_kind if report_kind != "premarket" else "morning")
    provider = str(cfg.get("provider") or "")
    model = str(cfg.get("model") or "")
    return {
        "report_kind": report_kind,
        "active": active,
        "suitable": suitable,
        "provider": provider,
        "model": model,
    }


def render_deepseek_principle_markdown() -> str:
    return "\n".join(
        [
            "### 🔑 使用原则：计算用代码，解读用模型",
            "",
            f"- {DEEPSEEK_USAGE_PRINCIPLE}",
            "- **解读类落点**：仅翻译/归纳已算好的数字与规则，不新增数值。",
            "- **离线研参落点**：what-if/harness 寻优仅产出研参建议，须经代码 clamp/apply 写入 policy，不直驱下单。",
        ]
    ).strip()


def _render_scenario_table(
    rows: list[dict[str, str]],
    *,
    header: tuple[str, str, str],
) -> list[str]:
    if not rows:
        return []
    lines = [
        "",
        f"| {header[0]} | {header[1]} | {header[2]} |",
        "|------|------|----------|",
    ]
    for row in rows[:8]:
        lines.append(f"| {row['name']} | {row['landing']} | {row['suitable_when']} |")
    lines.append("")
    return lines


def render_deepseek_landing_markdown(
    report_kind: str,
    *,
    settings: Optional[dict[str, Any]] = None,
    runtime: Optional[dict[str, Any]] = None,
) -> str:
    if not deepseek_landing_card_enabled(settings):
        return ""
    snap = build_deepseek_landing_snapshot(report_kind, settings=settings, runtime=runtime)
    active = snap.get("active") or []
    suitable = snap.get("suitable") or []
    if not active and not suitable:
        return ""

    active_interpret = [r for r in active if r.get("role") == _ROLE_INTERPRET]
    active_offline = [r for r in active if r.get("role") == _ROLE_OFFLINE]
    suitable_interpret = [r for r in suitable if r.get("role") == _ROLE_INTERPRET]
    suitable_offline = [r for r in suitable if r.get("role") == _ROLE_OFFLINE]

    lines = [
        "## 🤖 DeepSeek 引入场景与落地点",
        "",
        "_说明本报告链路中 DeepSeek 的适用场景与当前落点；不改变既有卡片结构与内容规范。_",
        "",
        render_deepseek_principle_markdown(),
        "",
    ]
    if active_interpret:
        lines.append("### ✅ 已落地 · 解读类（模型只翻译，不算数）")
        lines.extend(
            _render_scenario_table(
                active_interpret,
                header=("场景", "落点", "适用说明"),
            )
        )
    if active_offline:
        lines.append("### ✅ 已落地 · 离线研参（非实盘决策，代码 clamp 后写入）")
        lines.extend(
            _render_scenario_table(
                active_offline,
                header=("场景", "落点", "适用说明"),
            )
        )
    if suitable_interpret:
        lines.append("### 💡 适合引入 · 解读类")
        lines.extend(
            _render_scenario_table(
                suitable_interpret,
                header=("场景", "建议落点", "触发条件"),
            )
        )
    if suitable_offline:
        lines.append("### 💡 适合引入 · 离线研参")
        lines.extend(
            _render_scenario_table(
                suitable_offline,
                header=("场景", "建议落点", "触发条件"),
            )
        )

    provider = snap.get("provider") or "deepseek"
    model = snap.get("model") or "—"
    lines.extend(
        [
            "### ⚙️ 配置入口",
            f"- 叙事：`llm_narrative.jobs.{report_kind if report_kind != 'premarket' else 'morning'}` · provider={provider} · model={model}",
            "- 寻优：`harness_evolution.llm_optimize` · 各 `*_whatif.llm_optimize`",
            "- 密钥：`agent-reach configure --key=deepseek-key`",
        ]
    )
    return "\n".join(lines).strip()


def append_deepseek_landing_report_section(
    sections: list[ReportSection],
    *,
    report_kind: str,
    settings: Optional[dict[str, Any]] = None,
    runtime: Optional[dict[str, Any]] = None,
    renumber: Optional[Callable[[list[ReportSection]], None]] = None,
) -> list[ReportSection]:
    body = render_deepseek_landing_markdown(report_kind, settings=settings, runtime=runtime)
    if not body.strip():
        return sections
    out = list(sections)
    out.append(ReportSection(category=_CATEGORY, title="", body=body.strip()))
    if renumber:
        renumber(out)
    return out


def append_deepseek_landing_label_section(
    sections: list[Any],
    *,
    report_kind: str,
    label: str = "DeepSeek场景",
    settings: Optional[dict[str, Any]] = None,
    runtime: Optional[dict[str, Any]] = None,
    section_factory: Callable[[str, str], Any],
) -> list[Any]:
    body = render_deepseek_landing_markdown(report_kind, settings=settings, runtime=runtime)
    if not body.strip():
        return sections
    out = list(sections)
    out.append(section_factory(label, body.strip()))
    return out


def push_deepseek_landing_card(
    config: Any,
    settings: dict[str, Any],
    *,
    report_kind: str,
    runtime: Optional[dict[str, Any]] = None,
    title_suffix: str = "",
) -> Optional[dict[str, Any]]:
    """Standalone Feishu card (e.g. after intraday narrative)."""
    if not deepseek_landing_card_enabled(settings):
        return None
    body = render_deepseek_landing_markdown(report_kind, settings=settings, runtime=runtime)
    if not body.strip():
        return None
    from agent_reach.integrations.feishu import send_card

    tpl_map = {
        "morning": "feishu_template_premarket",
        "close": "feishu_template_close",
        "midday": "feishu_template_midday",
        "weekly": "feishu_template_weekly",
        "forecast": "feishu_template_forecast",
        "intraday": "feishu_template_intraday",
    }
    tpl_key = tpl_map.get(report_kind, "feishu_template_intraday")
    tpl = (settings.get("report") or {}).get(tpl_key, "blue")
    title = _CARD_LABEL + (f" · {title_suffix}" if title_suffix else "")
    return send_card(config, title, body, template=tpl)
