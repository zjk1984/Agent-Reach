---
name: daily_run_skill
description: >
  股票大师每日复盘与热门标的分析技能。
  使用 agent-reach 和网页抓取能力（Jina Reader、V2EX API 等）分析国内外时事政治与政策、热点产业新闻、相关舆情，
  并收集大宗商品、石油、美元汇率波动，同时联动美股、新加坡富时中国A50/金龙指数、港股及港股通南北向资金动向，自动定位热门股票代码，
  然后调用 daily_stock_analysis (DSA) 自动化拉取 K 线并执行多市场共振与技术面融合的 AI 决策分析。
triggers:
  - analyze: 股票大师/每日复盘/股票分析/大盘复盘/热门方向/分析股票/分析市场/复盘/分析
  - stock: 股票/个股/板块/技术面/K线/均线
  - macro: 宏观/政策/时事/政治/大宗商品/石油/美元/汇率/舆情/美股/港股/外资/北向/南向/金龙指数
metadata:
  openclaw:
    homepage: https://github.com/Panniantong/Agent-Reach
---

# 股票大师每日复盘与热门标的分析技能 (daily_run_skill)

本技能定义了如何作为**股票大师**，结合 **agent-reach** 的网页抓取能力定位国内外时事政治、产业政策、大宗商品（石油等）、美元汇率及舆情，并联动**美股、新加坡金龙指数、港股及港股通南北向资金动向**，调用 **daily_stock_analysis (DSA)** 执行自动化 K 线拉取、多市场共振与技术面融合的 AI 决策分析。

## 🚀 自动化工作流

### 第一步：宏观、全球多市场联动与资金流向数据收集 (通过 agent-reach 网页抓取)
1. **时事政治与产业政策：** 抓取主流财经媒体（如东方财富网、新华网财经）的最新宏观政策、证监会新规及产业扶持政策：
   ```bash
   # 抓取最新宏观政策与资讯精华
   curl -s "https://r.jina.ai/https://finance.eastmoney.com/a/cywjh.html"
   ```
2. **全球多市场共振（美股、港股、金龙指数）：** 实时抓取美股三大指数（纳斯达克、标普500、道琼斯）、纳斯达克金龙中国指数（HXC）、新加坡富时中国 A50 指数、以及恒生指数（HSI）的最新走势，研判全球中概股情绪：
   ```bash
   # 抓取东方财富全球市场及中概股实时行情
   curl -s "https://r.jina.ai/https://global.eastmoney.com/"
   ```
3. **港股通与南北向资金动向：** 实时监控港股通南向资金流入、北向资金（外资）流向，研判主力资金的真实态度与跨市场套利动向：
   ```bash
   # 抓取沪深港通资金流向排行
   curl -s "https://r.jina.ai/https://data.eastmoney.com/hsgt/index.html"
   ```
4. **大宗商品、石油与美元汇率：** 实时抓取全球大宗商品（布伦特原油、WTI 原油、黄金）及美元指数（USDX）、离岸人民币（USD/CNH）的最新波动。
5. **产业新闻与社交舆情：** 结合 **V2EX API**、**小红书** 或 **Twitter** 监控极客社区与大众对于前沿科技（AI、算力、先进封装）的真实舆情热度。

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

### 第四步：多市场共振与技术面融合的 AI 决策分析 (通过 DSA Pipeline)
1. 确保在 [Cursor Dashboard → Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents) 中配置了 `GEMINI_API_KEY` 或 `OPENAI_API_KEY`。
2. 运行完整分析流水线，将收集到的**美股/港股共振、金龙指数表现、南北向资金流向、大宗商品、美元汇率**作为上下文注入 Prompt，生成包含**核心结论、评分、趋势预测、买卖点位、风险警报、催化因素、操作检查清单**的精美 Markdown 报告：
   ```bash
   cd /tmp/daily_stock_analysis
   .venv/bin/python main.py --stocks 603986,688008,000725,002371,688256 --no-market-review --no-notify --force-run
   ```

---

## 📊 股票大师多市场共振与技术面量化决策模型

本模型将**全球多市场共振因子**与**技术指标**深度融合，作为每日买卖操作的最高准则：

| 全球共振因子 (美股/港股/资金) | 宏观因子 (美元/大宗) | 技术面均线 (MA5/MA20) | 20日价格位置 | 操盘策略 | 典型案例 |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **金龙指数/A50大涨** + **南北向资金大幅流入** | 美元走弱 / 人民币升值 | **强烈多头** (收盘>MA20 且 MA5>MA20) | **40% - 60%** (合理区间) | **强烈买入 / 重仓布局** | `688008` 澜起科技 (DDR5高景气) |
| **美股科技股(费半)大涨** + **外资(北向)流入** | 产业政策利好 | **多头趋势** (收盘>MA20) | **50% - 60%** (中位) | **防守型买入 / 顺周期配置** | 兆易创新 (存储芯片) |
| **美股大跌** + **外资(北向)大幅净流出** | 美元指数走强 | **强烈多头** (收盘>MA20 且 MA5>MA20) | **>70%** (偏高) | **等回踩 MA5/MA20，不追高** | `000725` 京东方A (玻璃基板热点) |
| **中概股暴跌** + **南北向资金全线流出** | 全球流动性收紧 | **震荡/破位** (收盘<MA20) | **<40%** (偏低) | **严格风控，暂时观望** | `688256` 寒武纪 (算力回调) |

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
