# Daily-run 热点新闻（60s API 自建）

daily-run 宏观采集会从 [60s API](https://github.com/vikiboss/60s) 拉取多平台热搜与「每天 60 秒读懂世界」要闻，并匹配持仓/板块关键词。

## 一键自建（推荐）

```bash
# 完整 bootstrap（含 portfolio + mcporter + 60s）
bash scripts/daily-run-local-setup.sh

# 仅部署 60s
bash scripts/60s-local-setup.sh
# 或
python3 -m agent_reach.cli daily-run hot-news install
```

默认 Docker 映射：**宿主机 `8787` → 容器 `4399`**，容器名 `agent-reach-60s`，镜像 `vikiboss/60s:latest`。

## 常用命令

```bash
# 查看本地 60s / 公共 fallback 状态
python3 -m agent_reach.cli daily-run hot-news status

# 强制重建容器
python3 -m agent_reach.cli daily-run hot-news install --force

# 停止容器
python3 -m agent_reach.cli daily-run hot-news stop

# 停止并删除容器
python3 -m agent_reach.cli daily-run hot-news stop --remove
```

## 配置

安装后写入 `~/.agent-reach/daily_run_settings.json`：

```json
"hot_news": {
  "enabled": true,
  "base_urls": ["http://127.0.0.1:8787", "https://60s.viki.moe"],
  "platforms": ["60s", "weibo", "zhihu", "it-news"]
}
```

- 优先本地 `127.0.0.1:8787`；不可达时自动 fallback 到公共实例
- 缓存目录：`~/.agent-reach/daily_run/cache/hot_news_*.json`

## 无 Docker 时

若本机无 Docker，hot news 仍可用（走 `https://60s.viki.moe`）。如需完全离线/私有，请自行部署 60s 并确保 health 可访问。

## 验证

```bash
curl -sf 'http://127.0.0.1:8787/v2/60s?encoding=json' | head
python3 -m agent_reach.cli daily-run hot-news status
```

完整 daily-run 文档见仓库 `agent_reach/skill/daily_run_skill.md`。
