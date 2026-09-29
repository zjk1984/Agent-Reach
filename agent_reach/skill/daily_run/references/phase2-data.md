## 🔬 Phase-2 数据增强与验证（AKShare + 报告验证 + 回测）

### AKShare 结构化兜底

当 Jina/DSA 不稳定时，用 AKShare 拉取行情并 enrich snapshot：

```bash
pip install 'agent-reach[daily-run]'   # 或 pip install akshare
agent-reach daily-run fetch --code 688008 -o /tmp/snapshot.json
agent-reach daily-run evaluate -i /tmp/snapshot.json
```

自动填充：`price` · `ma20` · `position_20d` · `volume_ratio` · `sources.quote`

### 历史报告验证（收盘复盘）

对比早盘基线 vs 收盘现状，检验 MSS 预测区间与标签变化：

```bash
agent-reach daily-run verify \
  -b config/daily_run_snapshot.example.json \
  -c /tmp/eod_snapshot.json

# 验证并推送飞书紫色卡片
agent-reach daily-run verify -b morning.json -c eod.json --push
```

输出：价格/MSS/标签变化、预测命中与否、偏差拆解、明日建议。

### MSS 规则回测

验证「MSS≥50 买入 / MSS<40 卖出」历史表现：

```bash
agent-reach daily-run backtest -i config/daily_run_history.example.json
```

示例 history 格式：`[{ "date", "mss", "price", "return" }, ...]`

### D3 盘中宽度 fallback（东财 clist）

盘中 TSP / Panel / D3 连板天梯抓取顺序（与收盘 `market_review` 对齐）：

1. **akshare 涨跌停池** — 权威：连板数、炸板池、精确涨跌停
2. **东财 clist → analyze_emotion** — 宽度 + 近似涨跌停（≥9.8%），无需 cookie
3. **akshare legu + 前日 pool 重试** — enrich 连板/炸板
4. **雪球宽度** — 仅 up/down/flat（需 cookie）
5. **market_review 磁盘缓存**

配置：`market_review.eastmoney_breadth_fallback` · `tsp_quant.intraday.eastmoney_breadth_fallback`（默认 true）。

**能力边界：** 东财 clist 无真实炸板池与连板数；`ladder_degraded` / `limit_degraded` 会在 Panel 与 D3 provenance 标注。收盘 akshare 池落盘后为权威快照。

---
