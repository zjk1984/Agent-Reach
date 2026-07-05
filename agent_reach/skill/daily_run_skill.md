---
name: daily-run-skill
description: >
  股票大师每日复盘与热门标的分析技能。
  结合 agent-reach 抓取全网最新科技/存储/玻璃基板等行业资讯，
  并调用 daily_stock_analysis (DSA) 自动化拉取 K 线数据、计算 MA 均线/量比/20日位置等技术指标，
  最后结合大模型生成深度的个股 AI 决策报告与操作策略。
triggers:
  - analyze: 每日复盘/股票分析/大盘复盘/热门方向/分析股票/分析市场/复盘/分析
  - stock: 股票/个股/板块/技术面/K线/均线
metadata:
  openclaw:
    homepage: https://github.com/Panniantong/Agent-Reach
---

# 股票大师每日复盘与热门标的分析技能 (daily-run-skill)

本技能定义了如何结合 **agent-reach** 抓取全网最新科技/存储/玻璃基板等行业资讯，并调用 **daily_stock_analysis (DSA)** 自动化拉取 K 线数据、计算 MA 均线/量比/20日位置等技术指标，最后结合大模型生成深度的个股 AI 决策报告与操作策略。

## 🚀 自动化工作流

### 第一步：全网热门方向与资讯调研 (通过 agent-reach)
1. 使用 **Jina Reader** 抓取主流财经媒体（如东方财富网）的最新科技、半导体、存储芯片、玻璃基板等板块的资金流向与利好催化：
   ```bash
   # 抓取最新资讯精华
   curl -s "https://r.jina.ai/https://finance.eastmoney.com/a/cywjh.html"
   
   # 抓取特定板块（如玻璃基板）的最新布局文章
   curl -s "https://r.jina.ai/https://finance.eastmoney.com/a/202607043794208253.html"
   ```
2. 结合 **V2EX API** 监控全网极客/开发者社区对于 AI、算力、前沿科技的讨论热度：
   ```bash
   curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"
   ```

### 第二步：数据拉取与技术指标计算 (通过 daily_stock_analysis)
1. 进入 `daily_stock_analysis` 目录，配置自选股列表并执行 **dry-run** 拉取最新 42 日 K 线数据（系统会自动通过 TencentFetcher 兜底拉取并存入 SQLite 数据库）：
   ```bash
   cd /tmp/daily_stock_analysis
   
   # 修改 .env 中的自选股列表
   sed -i 's/STOCK_LIST=.*/STOCK_LIST=000725,300323,002273,688499,603986,688008,002371,688256/' .env
   
   # 执行 dry-run 数据收集与入库（不消耗大模型 Token）
   .venv/bin/python main.py --dry-run --stocks 000725,300323,002273,688499,603986,688008,002371,688256 --no-market-review --no-notify --force-run
   ```

### 第三步：生成技术面深度穿透指标
1. 读取 `stock_analysis.db` 数据库中的 `stock_daily` 表计算 MA5、MA20、20日价格相对位置（20日最高价与最低价区间内的百分比位置）、量比以及 5 日累计涨跌幅：
   ```python
   # 核心计算逻辑：
   # 20日位置 = (最新收盘价 - 20日最低价) / (20日最高价 - 20日最低价) * 100
   # 趋势状态 = '强烈多头' (收盘 > MA20 且 MA5 > MA20) | '震荡' | '空头'
   ```

### 第四步：大模型 AI 决策分析 (通过 DSA Pipeline)
1. 确保在 [Cursor Dashboard → Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents) 中配置了 `GEMINI_API_KEY` 或 `OPENAI_API_KEY`。
2. 运行完整分析流水线，生成包含**核心结论、评分、趋势预测、买卖点位、风险警报、催化因素、操作检查清单**的精美 Markdown 报告：
   ```bash
   cd /tmp/daily_stock_analysis
   .venv/bin/python main.py --stocks 603986,688008,000725,002371,688256 --no-market-review --no-notify --force-run
   ```

---

## 📊 股票大师核心决策模型 (技术面分级)

| 均线趋势 (MA5/MA20) | 20日价格位置 | 5日累计涨跌 | 操盘策略 | 典型案例 (2026-07-03) |
| :--- | :---: | :---: | :--- | :--- |
| **强烈多头** (收盘>MA20 且 MA5>MA20) | **40% - 60%** (合理区间) | 逆势抗跌 / 小幅回调 | **逢低布局 / 强烈买入** | `688008` 澜起科技 (位置41%, 5日+4.0%) |
| **多头趋势** (收盘>MA20) | **50% - 60%** (中位) | 剧烈超跌 (<-10%) | **黄金坑回调 / 分批吸纳** | `603986` 兆易创新 (位置57%, 5日-11.6%) |
| **强烈多头** (收盘>MA20 且 MA5>MA20) | **>70%** (偏高) | 涨幅过大 | **等回踩 MA5/MA20，不追高** | `000725` 京东方A (位置72%, 5日+8.1%) |
| **震荡/破位** (收盘<MA20) | **<40%** (偏低) | 持续走弱 | **暂时观望，等企稳** | `688256` 寒武纪 (位置37%, 5日-6.6%) |

---

## 🛠️ 运维与排障指南

### 1. 提示 "LLM API Key 未配置"
*   **原因：** Cursor Cloud Agent 运行在隔离沙箱中，新配置的 Secrets 无法在当前热会话中生效。
*   **解决办法：** 
    1. 确保在 [Cursor Dashboard → Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents) 页面中配置了 `GEMINI_API_KEY` 或 `OPENAI_API_KEY`。
    2. **重启当前 Agent 任务**，使 Secrets 环境变量成功注入。

### 2. Efinance 历史 K 线接口失败 (RemoteDisconnected)
*   **原因：** 东方财富接口对高频连续请求有随机熔断限制。
*   **解决办法：** DSA 内部已集成多数据源自动切换。当 `EfinanceFetcher` 熔断后，系统会自动切换到 `TencentFetcher`（腾讯接口）进行兜底拉取，无需人工干预。
