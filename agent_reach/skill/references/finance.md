# 金融行情（雪球 xueqiu）

雪球（`agent_reach/channels/xueqiu.py`）提供行情报价、搜索与热门股/讨论帖抓取，Cookie 鉴权，
同 Twitter/XHS 一样遵循 **Cookie-Editor 浏览器导出** 方式（不支持 QR 扫码登录）。

## 配置 Cookie

```bash
# 推荐：一键从本机浏览器提取（同时会尝试提取 twitter/youtube/xhs 等其它平台）
agent-reach configure --from-browser chrome
# 提取前需先在浏览器登录 xueqiu.com

# 检查状态
agent-reach doctor --json
```

`configure` 没有单独的 `xueqiu-cookies` 子命令（不同于 `twitter-cookies`/`xhs-cookies`），
Cookie 只能通过 `--from-browser` 自动提取写入 `xueqiu_cookie` 配置项，或手工编辑
`~/.agent-reach/config.yaml`。

## 与 daily-run 的关系

雪球是 **daily-run 股票复盘 skill 的主要行情数据源**（价格锚点、持仓/观察池现价、Cookie 失效预警），
比作为独立"调研"渠道使用得更频繁：

- Cookie 失效时，**周日下周预测**首卡会展示 🍪 雪球 Cookie 预警（含重新导出步骤）
- `daily-run` 会在 forecast 工作流中自动做 Cookie 健康检查/浏览器刷新
  （`xueqiu_cookie_health.py`），无需手工干预
- **周日 forecast 前**（本机有桌面 DISPLAY 时）：会先 **headed Chrome 打开
  [xueqiu.com](https://xueqiu.com)** 续期登录态或等待人工登录，再
  `configure --from-browser chrome` 写入配置；无 DISPLAY 的 cron 主机则跳过打开浏览器
- 深入用法见 [daily_run skill](../daily_run_skill.md)，不要在这里重复造轮子

## 何时直接用 xueqiu 渠道（而非走 daily-run）

用户单独问「XX 股票现在多少钱」「雪球上大家怎么看 XX」等一次性行情/舆情查询时，
可直接调用本渠道读取报价或热门讨论帖；持仓级、周期性的复盘/预测请走 daily-run。
