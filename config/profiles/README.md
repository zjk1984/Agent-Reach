# Daily-run config profiles

Partial JSON overlays for `~/.agent-reach/daily_run_settings.json`. Merge by key (do not replace the whole file).

## `fund_ambush_watchlist.json` (Phase W1 / M9)

**Strategy:** watchlist-strategy-ambush (2026-10-20) — 主线埋伏，热点仅作风险扣分，不追标题入池。

### Prod merge keys (`~/.agent-reach/daily_run_settings.json`)

```jsonc
{
  "watchlist": {
    "hot_topic_adjust_enabled": false,
    "close_reorder_by_performance": false,
    "close_weak_rotation_enabled": true,
    "close_weak_rotation_max": 2,
    "negative_intel_remove_enabled": true,
    "xueqiu_hot_candidates_enabled": false,
    "xueqiu_search_candidates_enabled": true,
    "weekly_candidates_enabled": true
  },
  "plugins": {
    "eastmoney_screen_min_change_pct": 0.5
  }
}
```

- **close_reorder_by_performance:** `false` — 收盘不因涨跌幅重排观察池，减少「仅重排」类变更通知噪音（成员不变时 card 仍可通过 A 段说明原因）。
- **hot_topic_adjust_enabled:** `false` — close 不再因 60s/热词 **加** 观察池；负面公告/新闻剔除仍由 `negative_intel_remove_enabled` 负责。
- **xueqiu_hot_candidates_enabled:** `false` — 关闭雪球热榜入池；**xueqiu_search** 保留作低权重补充。
- **eastmoney_screen_min_change_pct:** `0.5`（W1 用 1.0；进一步降低 screen 最低涨幅门槛，埋伏 profile 更偏温和变动；repo 默认仍为 1.0）。
- **weekly_candidates + sector_pools:** 周六 weekly 与静态 sector 池仍是观察池主来源（manifest 权重说明见策略 doc §3 W1）。

**Do not merge via this profile:** `data_audit.*`, `intraday.technical_watch.min_cash_ratio_cap.attack_min_cash_ratio` — 执行链 gate 不在 W1 范围。

Apply snippet:

```bash
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.agent-reach' / 'daily_run_settings.json'
prof = json.loads(pathlib.Path('config/profiles/fund_ambush_watchlist.json').read_text())
user = json.loads(p.read_text()) if p.exists() else {}
def deep_merge(a, b):
    for k, v in b.items():
        if k.startswith('_'): continue
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep_merge(a[k], v)
        else:
            a[k] = v
    return a
deep_merge(user, prof)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(user, ensure_ascii=False, indent=2) + '\n')
print('merged', p)
"
```

Run from repo root after `git pull`; adjust paths if needed.

## `fund_moderate_cash.json` (Phase C1)

**Strategy:** 持有人反馈 ~83% 现金偏高、非熊市 — 降低 **现金地板** 与 **min_cash_ratio_cap**，提高 **deploy_signal** 弱/中档 deploy，可选放宽 **playbook 总仓 cap**；**不**关闭 gate 买入或 risk block，**不**恢复热点入池。

### Prod merge keys (`~/.agent-reach/daily_run_settings.json`)

Apply **after** W1 ambush keys if both profiles are used. Merge snippet (prod values):

```jsonc
{
  "thresholds": { "min_cash_ratio": 0.28 },
  "harness": {
    "min_cash_ratio_mode": "fixed",
    "reading_signals": {
      "mode": "fixed",
      "recovery_min_mss": 50.0,
      "recovery_min_lookback": 50.0,
      "recovery_min_delta": 3.0
    }
  },
  "intraday": {
    "technical_watch": {
      "min_cash_ratio_cap": {
        "register_min_cash_ratio": 0.30,
        "attack_min_cash_ratio": 0.20
      }
    }
  },
  "deploy_signal": {
    "weak_deploy_ratio": 0.35,
    "medium_deploy_ratio": 0.55
  },
  "playbook_contract": { "total_stock_weight_cap_pct": 52.0 },
  "watchlist": { "hot_topic_adjust_enabled": false }
}
```

- **min_cash_ratio_mode `fixed` + thresholds.min_cash_ratio 0.28:** 停止 harness memory/policy 把现金地板抬到 0.45–0.50；有效储备目标约 **25–30%**（仍会被宏观 tier、持仓与 gate 抬高/压低）。
- **reading_signals `fixed` + 更低 recovery 阈值:** MSS ~56 非熊市更易识别「回暖/recovery」，便于放松 defensive trim，**不是**绕过买入 gate。
- **min_cash_ratio_cap:** 技术场景登记上限 0.30、进攻期 attack 地板 0.20（默认 0.50 / 0.35）。
- **deploy_signal:** 弱/中信号 deploy 0.35 / 0.55（默认 0.25 / 0.50）— 在 gate 通过后更快动用可 deploy 现金。
- **total_stock_weight_cap_pct 52:** 相对默认 37% 提高 playbook 总股票权重上限；tradeoff：集中度与单票 playbook 约束仍生效，需与持有人风险容忍一致。若只想降 floor 不动 cap，merge 时省略 `playbook_contract` 块。
- **hot_topic_adjust_enabled false:** 保持 W1，不恢复热点观察池 churn。

**Do not use this profile to:** 关闭 `data_audit.*`、禁用 `kronos_bearish_block_buy`、或把 `hot_topic_adjust_enabled` 设回 `true`。

Apply snippet:

```bash
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.agent-reach' / 'daily_run_settings.json'
prof = json.loads(pathlib.Path('config/profiles/fund_moderate_cash.json').read_text())
user = json.loads(p.read_text()) if p.exists() else {}
def deep_merge(a, b):
    for k, v in b.items():
        if k.startswith('_'): continue
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep_merge(a[k], v)
        else:
            a[k] = v
    return a
deep_merge(user, prof)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(user, ensure_ascii=False, indent=2) + '\n')
print('merged', p)
"
```

Run from repo root after `git pull`; adjust paths if needed.

## `fund_lean.json` (Phase M4 / AR-4)

**Strategy:** 低价值调整（2026-10-19）— 减 ClawHub/Exa/热榜飞书噪音，**不**削弱 data_audit、收盘 audit、买入 gate 或 ledger。

### Prod merge keys (`~/.agent-reach/daily_run_settings.json`)

Apply **after** W1 ambush (and optional C1 moderate cash) when prod still runs findskills、berkshire news_pulse 全 workflow、或 close Exa 研究。

```jsonc
{
  "findskills": { "enabled": false },
  "berkshire": {
    "news_pulse": {
      "enabled": true,
      "workflows": ["weekly"]
    }
  },
  "plugins": {
    "exa_research_on_close": false,
    "max_exa_queries": 2
  },
  "macro_collector": {
    "hot_stock_limit": 6,
    "hot_watch_stock_limit": 6,
    "fetch_hot_watch_stocks": false,
    "intraday_hot_cross_enabled": false,
    "intraday_exa_new_hot_enabled": false,
    "xueqiu_exa_research_enabled": false,
    "xueqiu_exa_search_research_enabled": false
  },
  "hot_news": {
    "platforms": ["60s", "weibo"],
    "limit_per_platform": 12,
    "base_urls": ["https://60s.viki.moe", "http://127.0.0.1:8787"],
    "sentiment_boost_per_hit": 1
  },
  "weekly_report": {
    "skill_learning": false,
    "exa_skill_research": false,
    "max_sector_queries": 2
  },
  "watchlist": { "hot_topic_adjust_enabled": false }
}
```

- **findskills `enabled: false`:** 盘中/周报不再克隆 Node、搜 ClawHub（`run_findskills_queries` 空返回）。
- **news_pulse `workflows: ["weekly"]`:** morning/midday/close/forecast 不再附「📡 新闻脉搏」与 Exa/Eastmoney pulse；`report_audit`、`investment_checklist`、thesis 等 **沿用 repo 默认，本 profile 不改**。
- **exa_research_on_close `false`:** 收盘专家链少一轮 Exa 研究（与 pulse 降 weekly 一致）。
- **macro_collector / hot_news:** 少拉热股交叉、雪球 Exa、60s 平台数；公网 `60s.viki.moe` 优先于本机 8787。
- **weekly_report:** 关 skill_learning / exa_skill_research，略降 sector Exa 查询上限。
- **hot_topic_adjust_enabled false:** 与 W1 一致，不单开热点入池。

**Do not merge via this profile:** `data_audit.*`、`thresholds.min_cash_ratio`、`harness.min_cash_ratio_mode`、`intraday.technical_watch.min_cash_ratio_cap`、`deploy_signal.*`、`playbook_contract.*` — gate / 现金埋伏 / deploy 走 W1/C1，不在 M4 动。

Apply snippet:

```bash
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.agent-reach' / 'daily_run_settings.json'
prof = json.loads(pathlib.Path('config/profiles/fund_lean.json').read_text())
user = json.loads(p.read_text()) if p.exists() else {}
def deep_merge(a, b):
    for k, v in b.items():
        if k.startswith('_'): continue
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep_merge(a[k], v)
        else:
            a[k] = v
    return a
deep_merge(user, prof)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(user, ensure_ascii=False, indent=2) + '\n')
print('merged', p)
"
```

Run from repo root after `git pull`; adjust paths if needed.
