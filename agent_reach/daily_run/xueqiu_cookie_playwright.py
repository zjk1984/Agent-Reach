# -*- coding: utf-8
"""Xueqiu cookie refresh via Playwright headed login (ticket-sniper pattern)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.xueqiu_cookie_health import (
    _find_chrome_binary,
    _has_gui_display,
    _has_xq_a_token,
    _reset_xueqiu_channel_cookies,
    _week_forecast_settings,
)

PLAYWRIGHT_ENGINE = "playwright/ticket-sniper"
DEFAULT_LOGIN_URL = "https://xueqiu.com/user/login"
DEFAULT_PROFILE_DIR = Path.home() / ".agent-reach" / "xueqiu_browser_profile"

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _profile_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    wf = _week_forecast_settings(settings)
    raw = str(wf.get("xueqiu_cookie_playwright_profile_dir") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_PROFILE_DIR


def _login_url(settings: Optional[dict[str, Any]] = None) -> str:
    wf = _week_forecast_settings(settings)
    return str(wf.get("xueqiu_cookie_browser_login_url") or DEFAULT_LOGIN_URL).strip()


def _cookies_to_header(cookies: list[Any]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in cookies or []:
        if isinstance(raw, dict):
            name = str(raw.get("name") or "")
            value = raw.get("value")
            domain = str(raw.get("domain") or "")
        else:
            name = str(getattr(raw, "name", "") or "")
            value = getattr(raw, "value", None)
            domain = str(getattr(raw, "domain", "") or "")
        if not name or value is None:
            continue
        if domain and "xueqiu" not in domain:
            continue
        if name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _launch_persistent_context(playwright: Any, *, profile_dir: Path, headed: bool) -> Any:
    """Launch Chrome persistent context; fall back like ticket-sniper lib/browser.mjs."""
    opts: dict[str, Any] = {
        "headless": not headed,
        "args": list(_LAUNCH_ARGS),
        "viewport": {"width": 1280, "height": 800},
        "user_agent": _USER_AGENT,
    }
    user_data_dir = str(profile_dir)

    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            **opts,
        )
    except Exception:
        pass

    chrome_bin = _find_chrome_binary()
    if chrome_bin:
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir,
                executable_path=chrome_bin,
                **opts,
            )
        except Exception:
            pass

    return playwright.chromium.launch_persistent_context(user_data_dir, **opts)


def refresh_xueqiu_cookie_via_playwright(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """
    Open a headed browser on the Xueqiu login page, wait for xq_a_token, persist cookies.

    Mirrors zjk1984/ticket-sniper ``scripts/login.mjs``: persistent profile, login URL,
    poll until session cookies appear, then save to agent-reach config.
    """
    wf = _week_forecast_settings(settings)
    url = _login_url(settings)
    profile_dir = _profile_dir(settings)
    headed = wf.get("xueqiu_cookie_browser_login_headed", True) is not False
    try:
        timeout_sec = max(10, int(wf.get("xueqiu_cookie_browser_login_timeout_sec", 120)))
    except (TypeError, ValueError):
        timeout_sec = 120
    try:
        poll_sec = max(2, int(wf.get("xueqiu_cookie_browser_login_poll_sec", 5)))
    except (TypeError, ValueError):
        poll_sec = 5

    browser_login: dict[str, Any] = {
        "job": "xueqiu_cookie_browser_login",
        "engine": PLAYWRIGHT_ENGINE,
        "method": "playwright-persistent",
        "browser": "chrome",
        "profile_dir": str(profile_dir),
        "url": url,
        "waited_sec": 0,
        "token_seen_in_browser": False,
    }

    if not playwright_available():
        return {
            "skipped": True,
            "success": False,
            "reason": "playwright_not_installed",
            "engine": PLAYWRIGHT_ENGINE,
            "message": "未安装 playwright，请 pip install 'agent-reach[daily-run]' 或 playwright>=1.40",
            "job": "xueqiu_cookie_refresh",
        }

    if headed and not _has_gui_display():
        return {
            "skipped": True,
            "success": False,
            "reason": "no_display",
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": "无 DISPLAY/WAYLAND，跳过 headed Playwright 登录",
            "job": "xueqiu_cookie_refresh",
        }

    profile_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    token_seen = False
    cookie_str = ""
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            context = _launch_persistent_context(
                playwright,
                profile_dir=profile_dir,
                headed=headed,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=min(60_000, timeout_sec * 1000))

                while time.monotonic() - started < timeout_sec:
                    cookies = context.cookies()
                    cookie_str = _cookies_to_header(cookies)
                    if _has_xq_a_token(cookie_str):
                        token_seen = True
                        time.sleep(min(3, poll_sec))
                        cookies = context.cookies()
                        cookie_str = _cookies_to_header(cookies)
                        break
                    time.sleep(poll_sec)
            finally:
                context.close()
    except Exception as exc:
        waited_sec = int(time.monotonic() - started)
        browser_login.update(
            skipped=False,
            success=False,
            reason="playwright_error",
            message=str(exc),
            waited_sec=waited_sec,
        )
        return {
            "skipped": False,
            "success": False,
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
        }

    waited_sec = int(time.monotonic() - started)
    browser_login["waited_sec"] = waited_sec
    browser_login["token_seen_in_browser"] = token_seen

    if not token_seen:
        browser_login.update(
            skipped=False,
            success=False,
            reason="timeout",
            message=(
                f"{PLAYWRIGHT_ENGINE} 已打开 {url}，但在 {timeout_sec}s 内未检测到 xq_a_token；"
                "请在浏览器窗口完成登录后重跑 forecast"
            ),
        )
        return {
            "skipped": False,
            "success": False,
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": browser_login["message"],
            "job": "xueqiu_cookie_refresh",
        }

    from agent_reach.config import Config

    cfg = config or Config()
    cfg.set("xueqiu_cookie", cookie_str)
    cfg.save()
    _reset_xueqiu_channel_cookies()

    n_cookies = len([p for p in cookie_str.split(";") if p.strip()])
    browser_login.update(
        skipped=False,
        success=True,
        reason="token_ready",
        message=f"{PLAYWRIGHT_ENGINE} 检测到 xq_a_token（等待 {waited_sec}s）",
    )
    return {
        "skipped": False,
        "success": True,
        "engine": PLAYWRIGHT_ENGINE,
        "browser_login": browser_login,
        "message": f"{n_cookies} cookies (含 xq_a_token，{PLAYWRIGHT_ENGINE})",
        "job": "xueqiu_cookie_refresh",
    }
