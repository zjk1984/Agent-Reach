# -*- coding: utf-8 -*-
"""Xueqiu cookie health probe for Sunday forecast alerts."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_CHROME_BINARIES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium-browser",
    "chromium",
)


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


def _week_forecast_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return dict((settings or {}).get("week_forecast") or {})


def _has_gui_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _find_chrome_binary() -> Optional[str]:
    for name in _CHROME_BINARIES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _chrome_profile_dir() -> Path:
    return Path.home() / ".config" / "google-chrome"


def _is_chrome_running() -> bool:
    try:
        proc = subprocess.run(
            ["pgrep", "-f", r"google-chrome|chromium"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _browser_xueqiu_cookie_string(browser: str) -> str:
    """Best-effort read of xueqiu cookies from a local browser profile."""
    try:
        from agent_reach.cookie_extract import extract_all

        extracted = extract_all(browser)
    except Exception:
        return ""
    return str((extracted.get("xueqiu") or {}).get("cookie_string") or "")


def _refresh_every_forecast(settings: Optional[dict[str, Any]] = None) -> bool:
    wf = _week_forecast_settings(settings)
    return wf.get("xueqiu_cookie_refresh_every_forecast", True) is not False


def _cookie_needs_browser_login(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> bool:
    """Return True when opening xueqiu.com in Chrome may help refresh/login."""
    wf = _week_forecast_settings(settings)
    if _refresh_every_forecast(settings):
        return True
    if wf.get("xueqiu_cookie_browser_login_skip_when_healthy", True) is False:
        return True
    health = check_xueqiu_cookie_health(config=config, settings=settings)
    status = str(health.get("status") or "ok")
    return status in {"missing", "expired", "expiring", "degraded"}


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def ensure_xueqiu_browser_session(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
    browser: Optional[str] = None,
) -> dict[str, Any]:
    """
    Open Chrome on xueqiu.com before cookie extraction so an existing login can
    refresh session cookies or the operator can sign in manually (headed desktop).

    Skips on headless cron hosts (no DISPLAY), when disabled in settings, or when
    cookie health is already OK and ``xueqiu_cookie_browser_login_skip_when_healthy``
    is true (default).
    """
    wf = _week_forecast_settings(settings)
    browser_name = str(browser or wf.get("xueqiu_cookie_refresh_browser") or "chrome").strip().lower()
    url = str(wf.get("xueqiu_cookie_browser_login_url") or "https://xueqiu.com").strip()
    headed = wf.get("xueqiu_cookie_browser_login_headed", True) is not False
    try:
        timeout_sec = max(10, int(wf.get("xueqiu_cookie_browser_login_timeout_sec", 120)))
    except (TypeError, ValueError):
        timeout_sec = 120
    try:
        poll_sec = max(2, int(wf.get("xueqiu_cookie_browser_login_poll_sec", 5)))
    except (TypeError, ValueError):
        poll_sec = 5

    base = {
        "job": "xueqiu_cookie_browser_login",
        "browser": browser_name,
        "url": url,
        "waited_sec": 0,
        "token_seen_in_browser": False,
        "chrome_was_running": False,
    }

    if wf.get("xueqiu_cookie_browser_login_enabled", True) is False:
        return {**base, "skipped": True, "success": False, "reason": "disabled", "message": "browser login disabled"}

    if headed and not _has_gui_display():
        return {
            **base,
            "skipped": True,
            "success": False,
            "reason": "no_display",
            "message": "无 DISPLAY/WAYLAND，跳过 headed Chrome 登录",
        }

    if browser_name != "chrome":
        return {
            **base,
            "skipped": True,
            "success": False,
            "reason": "unsupported_browser",
            "message": f"browser login 目前仅支持 chrome，当前={browser_name}",
        }

    if not _cookie_needs_browser_login(settings=settings, config=config):
        return {
            **base,
            "skipped": True,
            "success": True,
            "reason": "already_healthy",
            "message": "雪球 Cookie 健康，跳过 Chrome 打开",
        }

    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        return {
            **base,
            "skipped": True,
            "success": False,
            "reason": "chrome_not_found",
            "message": "未找到 google-chrome/chromium 可执行文件",
        }

    chrome_was_running = _is_chrome_running()
    launched_proc: subprocess.Popen[Any] | None = None
    if chrome_was_running:
        try:
            subprocess.run(
                [chrome_bin, "--new-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {
                **base,
                "skipped": False,
                "success": False,
                "reason": "open_failed",
                "chrome_was_running": True,
                "message": f"Chrome 已在运行，打开新窗口失败: {exc}",
            }
    else:
        profile_dir = _chrome_profile_dir()
        cmd = [chrome_bin, f"--user-data-dir={profile_dir}", "--profile-directory=Default", url]
        try:
            launched_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return {
                **base,
                "skipped": False,
                "success": False,
                "reason": "launch_failed",
                "message": f"启动 Chrome 失败: {exc}",
            }

    token_seen = False
    started = time.monotonic()
    while time.monotonic() - started < timeout_sec:
        cookie_str = _browser_xueqiu_cookie_string(browser_name)
        if _has_xq_a_token(cookie_str):
            token_seen = True
            # Brief dwell so session cookies settle before we close Chrome.
            time.sleep(min(3, poll_sec))
            break
        time.sleep(poll_sec)

    waited_sec = int(time.monotonic() - started)
    if launched_proc is not None:
        _terminate_process_tree(launched_proc)
        time.sleep(2)
    elif chrome_was_running:
        return {
            **base,
            "skipped": False,
            "success": token_seen,
            "reason": "chrome_running",
            "chrome_was_running": True,
            "waited_sec": waited_sec,
            "token_seen_in_browser": token_seen,
            "message": (
                "Chrome 已在运行：已打开 xueqiu.com 窗口；请关闭 Chrome 后重试 cookie 提取"
                if not token_seen
                else "Chrome 已在运行：检测到 xq_a_token，请关闭 Chrome 以便提取 Cookie"
            ),
        }

    if token_seen:
        message = f"Chrome 已打开 {url} 并检测到 xq_a_token（等待 {waited_sec}s）"
        return {
            **base,
            "skipped": False,
            "success": True,
            "reason": "token_ready",
            "waited_sec": waited_sec,
            "token_seen_in_browser": True,
            "chrome_was_running": False,
            "message": message,
        }

    return {
        **base,
        "skipped": False,
        "success": False,
        "reason": "timeout",
        "waited_sec": waited_sec,
        "token_seen_in_browser": False,
        "chrome_was_running": False,
        "message": (
            f"Chrome 已打开 {url} 但在 {timeout_sec}s 内未检测到 xq_a_token；"
            "请在窗口中手动登录后重跑 forecast"
        ),
    }


def _use_browser_use(settings: Optional[dict[str, Any]] = None) -> bool:
    wf = _week_forecast_settings(settings)
    return wf.get("xueqiu_cookie_use_browser_use", True) is not False


def render_xueqiu_cookie_refresh_markdown(
    refresh: Optional[dict[str, Any]] = None,
    *,
    health: Optional[dict[str, Any]] = None,
) -> str:
    """Feishu markdown summarizing Sunday forecast cookie refresh (always when attempted)."""
    data = dict(refresh or {})
    if not data or (data.get("skipped") and data.get("reason") == "disabled"):
        return ""

    from agent_reach.daily_run.xueqiu_cookie_browser_use import BROWSER_USE_ENGINE

    lines = ["## 🍪 雪球 Cookie 更新", ""]
    engine = str(data.get("engine") or BROWSER_USE_ENGINE)
    repo = str(data.get("repo") or "")
    if data.get("skipped"):
        lines.append(f"**状态：** ⏭ 跳过 — {data.get('message') or data.get('reason') or '未执行'}")
    elif data.get("success"):
        lines.append(f"**状态：** ✅ 成功")
        lines.append(f"**方式：** {engine}")
        if repo:
            lines.append(f"**仓库：** {repo}")
        if data.get("message"):
            lines.append(f"**详情：** {data['message']}")
        login = data.get("browser_login") or {}
        if login.get("url"):
            waited = login.get("waited_sec")
            profile = login.get("profile") or login.get("browser")
            extra = f"，等待 {waited}s" if waited is not None else ""
            lines.append(f"**会话：** {login['url']}（profile={profile}{extra}）")
    else:
        lines.append(f"**状态：** ❌ 失败")
        lines.append(f"**方式：** {engine}")
        if repo:
            lines.append(f"**仓库：** {repo}")
        lines.append(f"**详情：** {data.get('message') or '未知错误'}")

    health_data = health or {}
    post_status = str(health_data.get("status") or "")
    if post_status:
        status_label = {
            "ok": "✅ 有效",
            "missing": "⚠️ 未配置",
            "expired": "❌ 已过期",
            "expiring": "🟡 即将到期",
            "degraded": "🟠 异常",
        }.get(post_status, post_status)
        lines.extend(["", f"**刷新后探针：** {status_label} — {health_data.get('message', '')}"])

    return "\n".join(lines).strip()


def refresh_xueqiu_cookie_from_browser(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
    browser: Optional[str] = None,
) -> dict[str, Any]:
    """
    Sync Xueqiu cookie from a logged-in local browser into agent-reach config.

    Used before Sunday forecast when ``week_forecast.xueqiu_cookie_auto_refresh_from_browser``
    is enabled. Prefers browser-use (Chrome CDP) when ``xueqiu_cookie_use_browser_use`` is
    true; otherwise opens Chrome via subprocess and extracts via rookiepy / browser_cookie3.
    """
    wf = _week_forecast_settings(settings)
    if wf.get("xueqiu_cookie_auto_refresh_from_browser", True) is False:
        return {"skipped": True, "reason": "disabled", "job": "xueqiu_cookie_refresh"}

    if _use_browser_use(settings):
        from agent_reach.daily_run.xueqiu_cookie_browser_use import (
            BROWSER_USE_ENGINE,
            BROWSER_USE_REPO,
            browser_use_available,
            refresh_xueqiu_cookie_via_browser_use,
        )

        if browser_use_available():
            return refresh_xueqiu_cookie_via_browser_use(settings=settings, config=config)

        repo = str(wf.get("xueqiu_cookie_browser_use_repo") or BROWSER_USE_REPO).strip()
        return {
            "skipped": True,
            "success": False,
            "reason": "browser_use_not_installed",
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
            "message": (
                f"已启用 {BROWSER_USE_ENGINE}，但未找到 browser-use CLI 或 Python 包；"
                f"请 pip install git+https://github.com/{BROWSER_USE_REPO}.git，"
                "并确保 cron PATH 含 ~/.local/bin"
            ),
            "job": "xueqiu_cookie_refresh",
        }

    browser_name = str(browser or wf.get("xueqiu_cookie_refresh_browser") or "chrome").strip().lower()
    browser_login = ensure_xueqiu_browser_session(
        settings=settings,
        config=config,
        browser=browser_name,
    )
    chrome_running_hint = bool(
        browser_login.get("chrome_was_running") and browser_login.get("token_seen_in_browser")
    )

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
            "browser_login": browser_login,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
            "forced": _refresh_every_forecast(settings),
        }

    xueqiu_row = next((row for row in results if row[0] == "Xueqiu"), None)
    if xueqiu_row and xueqiu_row[1]:
        _reset_xueqiu_channel_cookies()
        message = xueqiu_row[2]
        if chrome_running_hint:
            message = f"{message}（Chrome 运行中提取成功）"
        return {
            "skipped": False,
            "success": True,
            "engine": "chrome-extract",
            "browser": browser_name,
            "browser_login": browser_login,
            "message": message,
            "job": "xueqiu_cookie_refresh",
            "forced": _refresh_every_forecast(settings),
        }

    if xueqiu_row:
        fail_msg = xueqiu_row[2]
        if chrome_running_hint:
            fail_msg = f"{fail_msg}；Chrome 已在运行，可关闭 Chrome 后重试"
        return {
            "skipped": False,
            "success": False,
            "browser": browser_name,
            "browser_login": browser_login,
            "message": fail_msg,
            "job": "xueqiu_cookie_refresh",
            "forced": _refresh_every_forecast(settings),
        }

    detail = "; ".join(f"{name}: {msg}" for name, ok, msg in results if not ok) or "未找到雪球 Cookie"
    if chrome_running_hint:
        detail = f"{detail}；Chrome 已在运行，可关闭 Chrome 后重试"
    return {
        "skipped": False,
        "success": False,
        "browser": browser_name,
        "browser_login": browser_login,
        "message": detail,
        "job": "xueqiu_cookie_refresh",
        "forced": _refresh_every_forecast(settings),
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
