# 决策 vs 绩效偏差分析 · 2026-09-17

> **触发方式：** 手工复盘（manual trigger）  
> **数据真源：** `~/.agent-reach/daily_run/` 生产数据  
> **组合当日：** 净值 ¥101,622（收盘）· 日盈亏 **¥-513（-0.50%）** · 成交 **2 笔**（ledger）/ 收盘卡统计 **6 笔**（含模拟/历史口径）  
> **当日 regime：** `defensive`（overlay_log · close_seed · week_open）

---

## 执行摘要

| # | 标的 | 用户假设 | 生产验证 | 判定 |
|---|------|----------|----------|------|
| 1 | 京东方A 000725 | 早盘卖 200@5.72，收盘 5.75，面板 +5.5%，减仓错误 | **部分确认** — 卖价/收盘/板块方向一致；早卖错失日内涨幅 | ❌ 偏差 |
| 2 | 澜起科技 688008 | 午盘 trim 未执行，-2.78%，基准 scan 卖 700 更优 | **确认** — 午盘/下午多次 blocked；早午反转未减仓 | ❌ 偏差 |
| 3 | 海能达 002583 | 09:46 卖 500@8.32，收盘 8.23，+¥94 | **确认** — ledger T1 09:46 CST，realized **+¥93.53** | ✅ 正确 |
| 4 | 中芯国际 688981 | 13:38 买入未入账，-1.89%，避损 | **确认** — buy 信号 blocked（buy_budget）；若买入约 **-¥78** | ✅ 正确 |

**收盘 whatif 总评（prod `llm_narrative.whatif_verdict`）：** 整体 **基准值更优**；已实现卖出 PnL 持平（+¥23），但 **盘中 scan 卖出股数** 基准 700 → 自进化 0（实际 700 股经 **defensive_trim** 路径成交）。

---

## 数据源索引

| 类型 | 路径 |
|------|------|
| 成交 ledger | `trade_ledger.jsonl`（T1/T2 @ 2026-09-17） |
| 收盘 handoff | `handoff/close_2026-09-17.json` |
| 收盘 run | `runs/2026-09-17/close_181548.json` |
| 午盘 run | `runs/2026-09-17/midday_123350.json` |
| 盘中 run（13:38） | `runs/2026-09-17/intraday_133830.json` |
| 验证块 | close run → `symbol_results[].result.verify` |
| overlay / regime | `overlay_log/2026-09-17.json` |
| 面板板块 | `market_review/2026-09-17.json` · BK1335 面板 |

---

## 1. 京东方A（000725）— 板块 rally 中防御性减仓

### 生产事实

| 字段 | 值 | 来源 |
|------|-----|------|
| 卖出 | **200 股 @ ¥5.7243** | `trade_ledger.jsonl` T2 · `2026-09-17T02:16:28Z` = **10:16 CST** |
| 已实现盈亏 | **-¥70.68**（-5.82%） | ledger · cost ¥5.9532 |
| 收盘 | **¥5.75 · +5.50%** | `handoff/close_2026-09-17.json` · verify |
| 早盘基线 | ¥5.45 · MSS 51.18「可做」 | verify `price_baseline` |
| 剩余持仓 | **400 股** | handoff positions |
| 板块 | 面板 BK1335 **+1.55%**（板块）；个股 **+5.5%** | market_review · verify |

### 决策链

1. **09:46** 同 regime 下先卖海能达（T1），系统进入 defensive_trim 模式。  
2. **10:16** T2 触发：`MSS预测偏离/偏差信号 + 趋势 falling` → 防御性减仓 200 股。  
3. **10:16 之后** 000725 趋势转 rising，MSS 升至 50+；13:08+ 多次 blocked：`sell_defensive_trim`（已 trim）+ `post_sell_cooldown` + `week_open_plan`。  
4. 收盘卡：**热股命中 京东方A 人气榜#9 +4.0%**，与卖后上涨一致。

### 偏差量化

| 场景 | 估算 |
|------|------|
| 已卖 200 股 vs 持有至收盘（卖价→收盘价） | **+¥5.14** 额外浮盈（较小） |
| 若 200 股参与全日 rally（基线价 5.45→收 5.75） | **~+¥60** 日内机会成本 |
| 相对 cost 的 realized loss | **-¥70.68**（成本口径仍亏） |

### 结论

**假设成立：** 在面板/个股 rally 日执行 falling-trend 防御 trim 属于 **sector-timing 误判**。系统未在 14:10 后 MSS≥50 时回补或停止减栏逻辑，导致「卖在转强前、涨在卖后」。

---

## 2. 澜起科技（688008）— 午盘 trim 未执行 · 自进化过保守

### 生产事实

| 字段 | 值 | 来源 |
|------|-----|------|
| 早盘 | **¥199.89 · +6.42%** | `morning_080642.json` snapshot |
| 午盘 | **¥194.67 · -2.61%**（相对开盘回吐） | `midday_123350.json` |
| 收盘 | **¥194.33 · -2.78%**（vs 早盘基线） | verify · handoff |
| 日盈亏（100 股） | **-¥556** | handoff holdings_ledger |
| 午盘 trade | **空 `{}`** | midday run · 无 trim |
| 当日 scan 卖出 | **0 股**（688008） | 无 ledger 记录 |

### 阻断记录（节选）

| 时间 (CST) | scan | block_kind | 原因摘要 |
|------------|------|------------|----------|
| 13:08 | S8 | `sell_week_open_hold_debounce` | 周日计划「持有」，defensive_trim 需 4/4 确认 |
| 13:38 | S9 | `sell_week_open_hold_debounce` | 同上 |
| 14:13 | S10 | `sell_week_open_hold_debounce` | 同上 |

### 与「baseline sell 700」的关系

收盘 **whatif_verdict**（prod）：

```
盘中卖出 scan：基准 700 股 → 自进化 0 股（差 -700 股，基准值更优）
```

- **700 股**为 **组合级 scan 路径** 合计（非 688008 单票持仓 100 股）。  
- 当日实际卖出 **500+200=700 股** 均经 **defensive_trim**（002583/000725），**scan 路径为 0**。  
- 对 **688008**：基准 scan 若在早盘 strength（+6%）触发减仓，理论可规避约 **(199.89−194.33)×100 ≈ ¥556** 回吐；自进化 **week_open hold + debounce** 全日 blocking，导致 **一股未卖**。

### 结论

**假设成立：** 午盘 trim 未执行；自进化参数（deploy_ratio 25%、week_open hold debounce、defensive regime）在 **高开低走** 场景下过保守，错失 morning→close 约 **¥556** 的 trim 窗口。

---

## 3. 海能达（002583）— 09:46 防御减仓

### 生产事实

| 字段 | 值 | 来源 |
|------|-----|------|
| 卖出 | **500 股 @ ¥8.3217** | ledger T1 · `01:46:22Z` = **09:46 CST** ✅ |
| 已实现 | **+¥93.53**（+2.3%） | ledger |
| 收盘 | **¥8.23 · -1.2%** | verify · handoff |
| 卖价 vs 收盘（500 股） | **+¥45.85** 价差优势 | 推算 |

### 决策链

`Harness MSS预测偏离/偏差信号 + 趋势 mixed` → defensive_trim → 后续 `sell_defensive_trim` 阻止重复卖出。

### 结论

**假设成立 ✅** — 时间、价格、盈亏方向与 prod 完全一致；为本日 **唯一正 realized 交易**。

---

## 4. 中芯国际（688981）— 13:38 买入未入账

### 生产事实

| 字段 | 值 | 来源 |
|------|-----|------|
| 观察池买入信号 | **buy · T6** @ 13:38 run | `intraday_133830.json` |
| block_kind | **`buy_budget`** | 可部署 ¥14,938 < 一手 200 股 (~¥23,838) |
| 收盘 | **¥118.62 · -1.89%**（vs 基线 120.9） | verify |
| 若强制买入 200@119.01 | 约 **-¥78** + 摩擦 ~¥71 | 推算 |

### 决策链

1. deploy_ratio **25%** + min_cash **10%**（harness 有效参数）压缩可部署预算。  
2. 688981 为 **观察池** 标的，一手门槛未满足 → 系统 **正确拒绝** 入账。  
3. 14:13 后 buy 信号消失，转为 hold。

### 结论

**假设成立 ✅** — 买入未入账属 **`buy_budget` 门禁**；在 -1.89% 收盘下属于 **有效避损**（~¥78）。

---

## 技能对齐修复建议（仅建议 · 未改代码）

> 对齐 `daily-run-code-walk` / harness 进化方向；需用户批准后实施。

### P0 — sector rally 与 defensive trim 冲突（000725）

| 建议 | 模块 | 说明 |
|------|------|------|
| **sector_mss_mismatch 门禁** | `protections/sector_mss_mismatch.py` | 当 `sector.change_pct > 0` 且个股 `change_pct` 高于板块中位数时，**暂停 falling-trend defensive_trim** |
| **trim 后 trend 反转回补评估** | `defensive_trim_guards.py` | T2 卖出后若 2 次 scan 内 MSS≥50 且 trend→rising，写入 playbook「禁止同日二次减栏」而非继续 block 新买入 |
| **harness memory** | close_improve | 记录「面板 rally 日 000725 trim 误判」供 Saturday weekly 写回 |

### P1 — 高开低走 hold debounce（688008）

| 建议 | 模块 | 说明 |
|------|------|------|
| **morning_high 回吐阈值** | `hold_debounce_guards.py` | 若 `(morning_price - current) / morning_price ≥ 4%`，**override** `sell_week_open_hold_debounce` 允许 trim |
| **midday 强制 re-eval** | `midday.py` / schedule | 午盘 job 对「早盘涨幅>5% 且午盘转负」持仓 **必须** 输出 trim 建议，不可 `{}` |
| **deploy_ratio 分场景** | harness policy | rally 日（emotion.score≥4）临时提高 **scan 路径** deploy_ratio，避免仅 defensive_trim 单通道 |

### P2 — 买入预算（688981 · 已正确）

| 建议 | 模块 | 说明 |
|------|------|------|
| **维持 buy_budget** | `portfolio_manager.py` | 当前行为正确；可选：观察池「半手」模拟记账便于 whatif，**不自动放宽** |
| **文档化** | playbook | 明确「预算不足 = 成功避损」计入 forecast_review 正向案例 |

### P3 — 验证与监控

```bash
# 建议纳入下次 code-walk / 周六 weekly
python3 .cursor/skills/daily-run-code-walk/scripts/run_walk.py
python3 -m agent_reach.cli daily-run harness show
```

- 新增 **decision_vs_performance** 日更手工模板（本文件）挂到 `docs/`  
- 收盘卡增加 **per-symbol block_kind 汇总** 行，避免 700 股组合级指标掩盖单票（688008）偏差

---

## 附录 · 关键 prod 摘录

### trade_ledger（2026-09-17）

```
T1 09:46 CST  sell 002583  500 @ 8.3217  realized +93.53
T2 10:16 CST  sell 000725  200 @ 5.7243  realized -70.68
```

### verify 摘要

```
000725  价格 +5.5%   MSS 51→49   可做→可做
688008  价格 -2.8%   MSS 52→48   可做→观察
002583  价格 -1.2%   MSS 51→48   可做→观察
688981  价格 -1.9%   MSS 51→48   可做→观察
```

### next_day_session_seed

```json
{
  "regime": "defensive",
  "defensive_trim": true,
  "daily_pnl": -513.25,
  "daily_pnl_pct": -0.5
}
```

---

*Generated: 2026-09-18 · manual trigger · no code changes*
