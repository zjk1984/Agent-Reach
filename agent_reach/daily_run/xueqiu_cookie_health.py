# -*- coding: utf-8
"""Xueqiu cookie health probe for Sunday forecast alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _cookie_from_config(config=None) -> tuple[str, str]:
    """Return (cookie_string, source_label)."""
    try:
        from agent_reach.config import Config

        cfg = config or Config()
        raw = str(cfg.get("xueqiu_cookie") or "").strip()
        if raw:
            return raw, "config"
    except Exception:
        pass
    import os

    env = str(os.environ.get("XUEQIU_COOKIE") or "").strip()
    if env:
        return env, "env"
    return "", "none"


def _config_path(config=None) -> Optional[Path]:
    try:
        from agent_reach.config import Config

        cfg = config or Config()
        return Path(cfg.config_path)
    except Exception:
        return None


def _cookie_config_age_days(config=None) -> Optional[int]:
    """Days since agent-reach config file was last updated (proxy for cookie refresh)."""
    path = _config_path(config)
    if path is None or not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - mtime).days)


def _cookie_max_age_days(settings: Optional[dict[str, Any]] = None) -> int:
    wf = (settings or {}).get("week_forecast") or {}
    try:
        return max(1, int(wf.get("xueqiu_cookie_max_age_days", 6)))
    except (TypeError, ValueError):
        return 6


def _has_xq_a_token(cookie_str: str) -> bool:
    if not cookie_str:
        return False
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if pair.startswith("xq_a_token=") and len(pair) > len("xq_a_token="):
            return True
    return False


def _probe_authenticated_api(config=None) -> tuple[bool, str]:
    """Probe login-sensitive hot-stock API (public quote check is insufficient)."""
    try:
        from agent_reach.channels import xueqiu as xq_mod

        xq_mod._ensure_cookies()
        ch = xq_mod.XueqiuChannel()
        stocks = ch.get_hot_stocks(limit=1, stock_type=10)
        if stocks:
            return True, "热股榜接口正常"
        return False, "热股榜返回空列表"
    except Exception as exc:
        return False, str(exc)


def check_xueqiu_cookie_health(
    *,
    config=None,
    settings: Optional[dict[str, Any]] = None,
    macro_signals: Optional[dict[str, Any]] = None,
    live_macro_fetch: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Probe Xueqiu API readiness for daily-run macro/forecast cards.

    Returns dict with keys: status, level, message, cookie_configured, has_xq_a_token, api_status.
    status: ok | missing | expired | expiring | degraded
    """
    cookie_str, source = _cookie_from_config(config)
    configured = bool(cookie_str)
    has_token = _has_xq_a_token(cookie_str)
    cookie_age_days = _cookie_config_age_days(config)
    max_age_days = _cookie_max_age_days(settings)

    api_status = "unknown"
    api_message = ""
    auth_ok = False
    auth_message = ""
    if configured and has_token:
        auth_ok, auth_message = _probe_authenticated_api(config)
        api_status = "ok" if auth_ok else "warn"
        api_message = auth_message
    else:
        try:
            from agent_reach.channels import xueqiu as xq_mod

            ch = xq_mod.XueqiuChannel()
            status, message = ch.check(config)
            api_status = status
            api_message = str(message or "")
        except Exception as exc:
            api_status = "error"
            api_message = str(exc)

    macro = macro_signals or {}
    macro_ok = bool(
        macro.get("sentiment_posts")
        or macro.get("hot_stocks")
        or macro.get("hot_watch_stocks")
        or macro.get("portfolio_hot_stocks")
    )

    if not configured and not has_token:
        out_status = "missing"
        level = "warn"
        message = "未配置雪球 Cookie，周日报告「雪球热门」可能为空"
    elif configured and not has_token:
        out_status = "expired"
        level = "warn"
        message = "雪球 Cookie 缺少 xq_a_token，请用 Cookie-Editor 重新导出"
    elif configured and has_token and not auth_ok:
        out_status = "expired"
        level = "warn"
        message = "雪球 Cookie 可能已过期或无效，请重新导出"
    elif configured and cookie_age_days is not None and cookie_age_days >= max_age_days:
        out_status = "expiring"
        level = "warn"
        message = (
            f"雪球 Cookie 已 {cookie_age_days} 天未更新（建议 ≤{max_age_days} 天续期），"
            "避免下周热帖/热股突然失效"
        )
    elif live_macro_fetch is False and configured:
        out_status = "degraded"
        level = "warn"
        message = "本次未拉到实时雪球热帖/热股（已回退周六缓存），建议复核 Cookie"
    elif api_status == "ok" or auth_ok:
        out_status = "ok"
        level = "info"
        message = "雪球 Cookie 有效，热帖/热股接口正常"
    elif api_status in {"warn", "error"}:
        out_status = "expired"
        level = "warn"
        message = "雪球 Cookie 可能已过期或无效，请重新导出"
    else:
        out_status = "degraded"
        level = "warn"
        message = api_message or "雪球 API 响应异常"

    if out_status == "ok" and not macro_ok and configured:
        out_status = "degraded"
        level = "warn"
        message = "Cookie 探针通过但未拉到热帖/热股，建议复核登录态"

    return {
        "status": out_status,
        "level": level,
        "message": message,
        "cookie_configured": configured,
        "cookie_source": source,
        "has_xq_a_token": has_token,
        "cookie_age_days": cookie_age_days,
        "cookie_max_age_days": max_age_days,
        "auth_probe_ok": auth_ok,
        "auth_probe_message": auth_message,
        "live_macro_fetch": live_macro_fetch,
        "api_status": api_status,
        "api_message": api_message,
        "macro_signals_ok": macro_ok,
    }


def _reset_xueqiu_channel_cookies() -> None:
    try:
        from agent_reach.channels import xueqiu as xq_mod

        xq_mod._cookie_jar.clear()
        xq_mod._cookies_initialized = False
    except Exception:
        pass


def refresh_xueqiu_cookie_from_browser(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
    browser: Optional[str] = None,
) -> dict[str, Any]:
    """
    Sync Xueqiu cookie from a logged-in local browser into agent-reach config.

    Used before Sunday forecast when ``week_forecast.xueqiu_cookie_auto_refresh_from_browser``
    is enabled. Does not perform interactive login — Chrome must already be signed in.
    """
    wf = (settings or {}).get("week_forecast") or {}
    if wf.get("xueqiu_cookie_auto_refresh_from_browser", True) is False:
        return {"skipped": True, "reason": "disabled", "job": "xueqiu_cookie_refresh"}

    browser_name = str(browser or wf.get("xueqiu_cookie_refresh_browser") or "chrome").strip().lower()
    try:
        from agent_reach.config import Config
        from agent_reach.cookie_extract import configure_from_browser

        cfg = config or Config()
        results = configure_from_browser(browser_name, cfg)
    except Exception as exc:
        return {
            "skipped": False,
            "success": False,
            "browser": browser_name,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
        }

    xueqiu_row = next((row for row in results if row[0] == "Xueqiu"), None)
    if xueqiu_row and xueqiu_row[1]:
        _reset_xueqiu_channel_cookies()
        return {
            "skipped": False,
            "success": True,
            "browser": browser_name,
            "message": xueqiu_row[2],
            "job": "xueqiu_cookie_refresh",
        }

    if xueqiu_row:
        return {
            "skipped": False,
            "success": False,
            "browser": browser_name,
            "message": xueqiu_row[2],
            "job": "xueqiu_cookie_refresh",
        }

    detail = "; ".join(f"{name}: {msg}" for name, ok, msg in results if not ok) or "未找到雪球 Cookie"
    return {
        "skipped": False,
        "success": False,
        "browser": browser_name,
        "message": detail,
        "job": "xueqiu_cookie_refresh",
    }


def render_xueqiu_cookie_alert_markdown(health: Optional[dict[str, Any]] = None, *, config=None) -> str:
    """Feishu markdown for Sunday forecast cookie alert (empty when healthy)."""
    data = health or check_xueqiu_cookie_health(config=config)
    status = str(data.get("status") or "ok")
    if status == "ok":
        return ""

    title = {
        "missing": "未配置",
        "expired": "已过期 / 无效",
        "expiring": "即将到期",
        "degraded": "异常",
    }.get(status, "需关注")

    lines = [
        "## 🍪 雪球 Cookie 预警",
        "",
        f"**状态：** {title} — {data.get('message', '')}",
        "",
        "**影响：** 周日预测卡「雪球热门」、宏观舆情、部分 MSS 情绪因子可能缺失或降级。",
        "",
        "### 获取 Cookie（推荐 Cookie-Editor）",
        "",
        "1. 在 Chrome 打开并登录 [xueqiu.com](https://xueqiu.com)",
        "2. 安装 [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) 扩展",
        "3. 点击扩展图标 → **Export** → **Header String**，复制整段 Cookie",
        "4. 写入 Agent Reach 配置（任选其一）：",
        "",
        "**方式 A — 编辑配置文件**",
        "",
        "```yaml",
        "# ~/.agent-reach/config.yaml",
        'xueqiu_cookie: "xq_a_token=...; u=...; ..."',
        "```",
        "",
        "**方式 B — 本地 Chrome 一键提取**（需本机已登录雪球）",
        "",
        "```bash",
        "python3 -m agent_reach.cli configure --from-browser chrome",
        "python3 -m agent_reach.cli doctor",
        "```",
        "",
        "**方式 C — 环境变量**（Cloud Agent / cron）",
        "",
        "```bash",
        "export XUEQIU_COOKIE='xq_a_token=...; u=...; ...'",
        "```",
        "",
        "更新后运行 `python3 -m agent_reach.cli doctor`，确认 **雪球** 渠道为 ✅。",
    ]
    age = data.get("cookie_age_days")
    if age is not None and status in {"expiring", "degraded", "expired"}:
        lines.extend(["", f"_配置上次更新：约 {age} 天前_"])
    detail = data.get("auth_probe_message") or data.get("api_message")
    if detail and status != "missing":
        lines.extend(["", f"_API 详情：{str(detail)[:180]}_"])
    return "\n".join(lines)
