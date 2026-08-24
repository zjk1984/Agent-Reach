# daily-run 错误与补跑

盘中/收盘/调度专用。通用平台错误见 [agent-reach errors.md](../../references/errors.md)。

## schedule / lock

| 信号 | 动作 |
|------|------|
| `lockfile` / 任务正在运行 | 确认 PID 已退出 → 删 lock；补跑加 `--force` |
| manifest 去重 skip | `schedule run <job> --force` |
| 并行 intraday 无 `--force` | 会 skip；勿同时手工+cron |

## MSS / 调仓文案

| 现象 | 说明 |
|------|------|
| 卡片「进攻阈值 50」 vs harness 45 | 研判应读 **effective_settings**；见 `harness_display` 页脚 |
| 摩擦惩罚阻断 | 预期收益 ≤ 交易成本门槛；非 bug |
| MSS<macro_veto 仍显示「可做」 | 查 audit Gate；禁止强行买入 |
| 涨停不买 / 跌停不卖 / 停牌标的被跳过 | `tradability.py` 硬门禁（`tradability_block_reason`）；非 bug，禁止绕过 |
| 决策带 `holding_lock_days` 锁仓拒绝主动卖出 | 正常风控；实际生效天数看 `effective_settings`，不是文档写死的固定值 |

## PnL / 现金对账

| 现象 | 说明 |
|------|------|
| 收盘 `close_code_review` 报「现金与 ledger 偏差」 | 已自动按 ledger 重算 cash/total/cash_ratio；查 `apply_portfolio_cash_reconcile` 日志 |
| 入金/出金后 portfolio 现金没变 | `daily-run capital deposit/withdraw` 默认自动同步；若之前用了 `--no-adjust-cash` 需手工核对 |
| `pnl history` 报「缺口」 | `detect_pnl_history_gaps` 发现交易日未记录当日盈亏；用 `daily-run pnl history --backfill` 补录 |
| 周报「累计」与收盘卡「总收益」对不上 | 两套口径：前者是净值逐日累加，后者是历史 FIFO 已实现+当前浮盈浮亏，属正常差异，非数据错误 |

## Feishu

| 信号 | 动作 |
|------|------|
| `FeishuError` | `~/.agent-reach/config.env` + config.yaml |
| 主卡有、AI 卡无 | 查 manifest `narrative_feishu`；`llm_narrative` 是否 disabled |

## 工具门禁（Exa / 60s）

- Exa：同 query **86400s** 内不重复（`exa_cache`）
- 60s：`http://127.0.0.1:8787` → fallback `https://60s.viki.moe`
- 盘中 intraday：**不**拉 Exa 全量；仅 quotes enrich

## 补跑命令

```bash
REPO="${REPO:-$PWD}"
${REPO}/venv/bin/python3 -m agent_reach.cli daily-run schedule run intraday --force
```

日志：`~/.agent-reach/daily_run/logs/cron-YYYY-MM-DD.log`
