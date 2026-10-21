# Daily-run config profiles

Partial JSON overlays for `~/.agent-reach/daily_run_settings.json`. Merge by key (do not replace the whole file).

## `fund_ambush_watchlist.json` (Phase W1 / M9)

**Strategy:** watchlist-strategy-ambush (2026-10-20) — 主线埋伏，热点仅作风险扣分，不追标题入池。

### Prod merge keys (`~/.agent-reach/daily_run_settings.json`)

```jsonc
{
  "watchlist": {
    "hot_topic_adjust_enabled": false,
    "close_weak_rotation_enabled": true,
    "close_weak_rotation_max": 2,
    "negative_intel_remove_enabled": true,
    "xueqiu_hot_candidates_enabled": false,
    "xueqiu_search_candidates_enabled": true,
    "weekly_candidates_enabled": true
  },
  "plugins": {
    "eastmoney_screen_min_change_pct": 1.0
  }
}
```

- **hot_topic_adjust_enabled:** `false` — close 不再因 60s/热词 **加** 观察池；负面公告/新闻剔除仍由 `negative_intel_remove_enabled` 负责。
- **xueqiu_hot_candidates_enabled:** `false` — 关闭雪球热榜入池；**xueqiu_search** 保留作低权重补充。
- **eastmoney_screen_min_change_pct:** `1.0`（原 3% 偏追高）— 东财 screen 候选更偏温和变动。
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
