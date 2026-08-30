# -*- coding: utf-8
"""Xueqiu cookie refresh via browser-use (Chrome CDP)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from agent_reach.daily_run.xueqiu_cookie_health import (
    _has_xq_a_token,
    _reset_xueqiu_channel_cookies,
    _week_forecast_settings,
)


def browser_use_available() -> bool:
    try:
        import browser_use  # noqa: F401

        return True
    except ImportError:
        return False


def _cdp_cookies_to_header(cookies: list[Any]) -> str:
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


async def _async_refresh_xueqiu_cookie(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    from browser_use import Browser

    wf = _week_forecast_settings(settings)
    url = str(wf.get("xueqiu_cookie_browser_login_url") or "https://xueqiu.com").strip()
    profile = str(
        wf.get("xueqiu_cookie_browser_use_profile")
        or wf.get("xueqiu_cookie_browser_profile")
        or "Default"
    ).strip()
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
        "engine": "browser-use",
        "browser": "chrome",
        "profile": profile,
        "url": url,
        "waited_sec": 0,
        "token_seen_in_browser": False,
    }

    browser = Browser.from_system_chrome(profile_directory=profile, headless=not headed)
    try:
        await browser.start()
        await browser.navigate_to(url)

        token_seen = False
        cookie_str = ""
        started = time.monotonic()
        while time.monotonic() - started < timeout_sec:
            cookies = await browser.cookies()
            cookie_str = _cdp_cookies_to_header(cookies)
            if _has_xq_a_token(cookie_str):
                token_seen = True
                await asyncio.sleep(min(3, poll_sec))
                cookies = await browser.cookies()
                cookie_str = _cdp_cookies_to_header(cookies)
                break
            await asyncio.sleep(poll_sec)

        waited_sec = int(time.monotonic() - started)
        browser_login["waited_sec"] = waited_sec
        browser_login["token_seen_in_browser"] = token_seen

        if not token_seen:
            browser_login.update(
                skipped=False,
                success=False,
                reason="timeout",
                message=(
                    f"browser-use 已打开 {url}，但在 {timeout_sec}s 内未检测到 xq_a_token；"
                    "请在 Chrome 窗口登录后重跑 forecast"
                ),
            )
            return {
                "skipped": False,
                "success": False,
                "engine": "browser-use",
                "browser": "chrome",
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
            message=f"browser-use 检测到 xq_a_token（等待 {waited_sec}s）",
        )
        return {
            "skipped": False,
            "success": True,
            "engine": "browser-use",
            "browser": "chrome",
            "browser_login": browser_login,
            "message": f"{n_cookies} cookies (含 xq_a_token，browser-use/CDP)",
            "job": "xueqiu_cookie_refresh",
        }
    except Exception as exc:
        browser_login.update(
            skipped=False,
            success=False,
            reason="browser_use_error",
            message=str(exc),
        )
        return {
            "skipped": False,
            "success": False,
            "engine": "browser-use",
            "browser": "chrome",
            "browser_login": browser_login,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
        }
    finally:
        try:
            await browser.stop()
        except Exception:
            try:
                await browser.close()
            except Exception:
                pass


def refresh_xueqiu_cookie_via_browser_use(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """Sync wrapper for Sunday forecast cookie refresh via browser-use."""
    if not browser_use_available():
        return {
            "skipped": True,
            "success": False,
            "reason": "browser_use_not_installed",
            "message": "未安装 browser-use，请 pip install browser-use 或关闭 xueqiu_cookie_use_browser_use",
            "job": "xueqiu_cookie_refresh",
            "engine": "browser-use",
        }
    return asyncio.run(_async_refresh_xueqiu_cookie(settings=settings, config=config))
