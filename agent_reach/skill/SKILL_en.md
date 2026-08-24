---
name: agent-reach
version: "1.5.0"
description: >
  MUST USE when user wants to research/search/look up/find anything on the
  internet — e.g. "research this topic", "do a deep dive on X", "search the
  web for X", "see what people say about X", "look this up".

  Also MUST USE when user mentions any platform or shares any URL/link:
  Twitter/X, Reddit, Facebook, Instagram, YouTube, GitHub, Bilibili, XiaoHongShu,
  Xiaoyuzhou Podcast, LinkedIn/jobs/recruiting, V2EX, Xueqiu (stocks), RSS.

  15 platforms, multi-backend routing (OpenCLI / per-platform CLIs / APIs).
  Zero config for 6 channels. Run `agent-reach doctor --json` to see which
  backend serves each platform right now.

  NOT for: writing reports/analysis/translation (this skill only FETCHES
  internet content); posting/commenting/liking (write operations); platforms
  that already have a dedicated skill installed (prefer that skill).
allowed-tools: Bash, Read, Grep, Glob
triggers:
  - research: research/deep dive/look into/investigate
  - search: search/look up/find/what do people say
  - social: xiaohongshu/xhs/twitter/x.com/bilibili/v2ex/reddit/facebook/instagram
  - career: jobs/recruiting/hiring/linkedin
  - dev: github/repo/code/gh/issue/pr/branch/commit
  - web: webpage/link/article/rss/read this/open this
  - video: youtube/video/podcast/subtitles/xiaoyuzhou/transcript/yt
  - finance: xueqiu/stock/stocks/quote/fund
metadata:
  openclaw:
    homepage: https://github.com/Panniantong/Agent-Reach
---

> 📖 **This is the compact English variant.** The canonical, most detailed and
> actively maintained doc is [SKILL.md](SKILL.md) (Chinese; commands themselves
> are language-neutral). If anything here looks incomplete or out of date,
> defer to `SKILL.md` and its `references/*.md`.

# Agent Reach — internet capability router

15 platforms, multiple backends each. **When this skill exists, use it for
these platforms — do not invent your own approach.**

## Standing rules (apply for the whole session)

1. **Health-check before acting**: for multi-backend/login-backed platforms (XiaoHongShu /
   Reddit / Bilibili / Twitter / Facebook / Instagram), run `agent-reach doctor --json` first and
   pick the command group matching each platform's `active_backend`.
2. **Announce what you use**: say "using agent-reach, platform X via backend Y"
   before starting.
3. **On failure, follow the retry chains in references/** — never guess
   commands.
4. **For broad research tasks**: combine platforms (Exa for web search +
   Twitter/Reddit for discussions + XiaoHongShu/Bilibili for Chinese
   perspectives), collect in parallel, then synthesize.
5. **Watch versions for the user**: after finishing a substantial
   multi-platform task, run `agent-reach check-update` (fast, one API call).
   If a new version exists, append one line to your wrap-up: "Agent Reach
   vX.Y.Z is available — paste this to me to update: 帮我更新 Agent Reach：
   https://raw.githubusercontent.com/Panniantong/agent-reach/main/docs/update.md".
   Never interrupt the current task to update; never nag about the same version twice.

## ⛔ FORBIDDEN (any environment)

| Forbidden | Reason |
|------|------|
| XiaoHongShu MCP `get_login_qrcode` / QR scan | Hangs in Cloud/cron; use Cookie-Editor or OpenCLI |
| Switching backends without running `doctor` first | Wastes quota; see errors.md |
| Writing persistent files in the agent workspace | Use `/tmp/` for temp, `~/.agent-reach/` for persistent |
| Modifying upstream open-source project source code | Agent Reach is a glue/routing layer only |
| Retrying the same error signal more than 2 times | See errors.md Retry budget |

## Routing table

| User intent | Category | Details |
|---------|------|---------|
| Web / code search / Exa | search | [references/search.md](references/search.md) |
| Failures / 401 / 429 / lock / retry | errors | [references/errors.md](references/errors.md) |
| XiaoHongShu / Twitter / Bilibili / V2EX / Reddit / Facebook / Instagram | social | [references/social.md](references/social.md) |
| Jobs / LinkedIn | career | [references/career.md](references/career.md) |
| GitHub / code | dev | [references/dev.md](references/dev.md) |
| Web pages / articles / RSS | web | [references/web.md](references/web.md) |
| YouTube / Bilibili / podcast transcripts | video | [references/video.md](references/video.md) |
| Xueqiu / stock quotes / finance | finance | [references/finance.md](references/finance.md) |

## Zero-config quick commands

```bash
# Exa web search
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'

# Read any web page
curl -s "https://r.jina.ai/URL"

# GitHub search
gh search repos "query" --sort stars --limit 10

# YouTube subtitles (NOTE: never use yt-dlp for Bilibili — see video.md)
yt-dlp --write-sub --skip-download -o "/tmp/%(id)s" "URL"

# V2EX hot topics
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"

# Bilibili search (bili-cli, no login needed)
bili search "query" --type video -n 5
```

## Login-backed platforms (pick by doctor's active_backend)

```bash
# Twitter search (twitter-cli preferred; retry chain in social.md)
twitter search "query" -n 10

# Reddit (NO zero-config path — OpenCLI or rdt-cli, login required)
opencli reddit search "query" -f yaml   # desktop
rdt search "query" --limit 10            # legacy/server

# XiaoHongShu (desktop prefers OpenCLI)
opencli xiaohongshu search "query" -f yaml

# Facebook / Instagram (desktop OpenCLI, browser session)
opencli facebook search "query" -f yaml
opencli facebook groups -f yaml
opencli instagram search "query" -f yaml       # user search
opencli instagram user USERNAME -f yaml        # recent posts from one user
```

## Environment check

```bash
# Channel availability + which backend serves each platform
agent-reach doctor --json
```

## Workspace rules

**Never create files in the agent workspace.** Use `/tmp/` for temporary
output and `~/.agent-reach/` for persistent data.

## Detailed references

Read the matching file when you need specifics (commands above cover the
common cases; references hold per-backend command groups, caveats, retry
chains — note: reference docs are written in Chinese, commands are universal):

- [Search](references/search.md) — Exa AI search
- [Errors](references/errors.md) — signal table, retry budget, lock/auth
- [Social](references/social.md) — XiaoHongShu, Twitter, Bilibili, V2EX, Reddit, Facebook, Instagram (multi-backend/login-backed groups)
- [Career](references/career.md) — LinkedIn
- [Dev](references/dev.md) — GitHub CLI
- [Web](references/web.md) — Jina Reader, RSS
- [Video](references/video.md) — YouTube, Bilibili, Xiaoyuzhou
- [Finance](references/finance.md) — Xueqiu (stock quotes); portfolio-level review lives in the daily_run skill

## Configure a channel

If a channel needs setup, fetch the install guide:
https://raw.githubusercontent.com/Panniantong/agent-reach/main/docs/install.md

The user only provides cookies / one extension click; the agent does the rest.
