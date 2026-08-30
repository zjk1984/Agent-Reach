# -*- coding: utf-8
"""Xueqiu cookie refresh via zjk1984/browser-use (CLI + CDP)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from typing import Any, Optional

from agent_reach.daily_run.xueqiu_cookie_health import (
    _has_xq_a_token,
    _reset_xueqiu_channel_cookies,
    _week_forecast_settings,
)

BROWSER_USE_REPO = "zjk1984/browser-use"
BROWSER_USE_ENGINE = "zjk1984/browser-use"


def _browser_use_repo(settings: Optional[dict[str, Any]] = None) -> str:
    wf = _week_forecast_settings(settings)
    return str(wf.get("xueqiu_cookie_browser_use_repo") or BROWSER_USE_REPO).strip()


def browser_use_cli_available() -> bool:
    return bool(shutil.which("browser-use"))


def browser_use_available() -> bool:
    if browser_use_cli_available():
        return True
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


def _parse_cli_json(stdout: str) -> Optional[dict[str, Any]]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _build_browser_use_cli_script(*, url: str, timeout_sec: int, poll_sec: int) -> str:
    return f"""
import json, time
ensure_real_tab()
new_tab({json.dumps(url)})
wait_for_load(min(30, {timeout_sec}))
deadline = time.time() + {timeout_sec}
has_token = False
cookies_out = []
page_url = ""
while time.time() < deadline:
    try:
        page_url = (page_info() or {{}}).get("url") or page_url
    except Exception:
        pass
    raw = cdp("Storage.getCookies")
    cookies_out = [c for c in raw.get("cookies", []) if "xueqiu" in (c.get("domain") or "")]
    if any(c.get("name") == "xq_a_token" and c.get("value") for c in cookies_out):
        has_token = True
        time.sleep(min(3, {poll_sec}))
        raw = cdp("Storage.getCookies")
        cookies_out = [c for c in raw.get("cookies", []) if "xueqiu" in (c.get("domain") or "")]
        break
    time.sleep({poll_sec})
print(json.dumps({{"has_xq_a_token": has_token, "cookies": cookies_out, "url": page_url}}, ensure_ascii=False))
""".strip()


def _refresh_via_browser_use_cli(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    wf = _week_forecast_settings(settings)
    url = str(wf.get("xueqiu_cookie_browser_login_url") or "https://xueqiu.com").strip()
    profile = str(
        wf.get("xueqiu_cookie_browser_use_profile")
        or wf.get("xueqiu_cookie_browser_profile")
        or "Default"
    ).strip()
    repo = _browser_use_repo(settings)
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
        "engine": BROWSER_USE_ENGINE,
        "repo": repo,
        "method": "browser-use-cli",
        "browser": "chrome",
        "profile": profile,
        "url": url,
        "waited_sec": 0,
        "token_seen_in_browser": False,
    }

    if not browser_use_cli_available():
        return {
            "skipped": True,
            "success": False,
            "reason": "browser_use_cli_missing",
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
            "message": f"未找到 browser-use CLI，请 pip install git+https://github.com/{BROWSER_USE_REPO}.git",
            "job": "xueqiu_cookie_refresh",
        }

    script = _build_browser_use_cli_script(url=url, timeout_sec=timeout_sec, poll_sec=poll_sec)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["browser-use"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 90,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        browser_login.update(
            skipped=False,
            success=False,
            reason="cli_timeout",
            message=str(exc),
            waited_sec=int(time.monotonic() - started),
        )
        return {
            "skipped": False,
            "success": False,
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
            "browser_login": browser_login,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
        }

    waited_sec = int(time.monotonic() - started)
    browser_login["waited_sec"] = waited_sec
    payload = _parse_cli_json(proc.stdout)
    stderr_tail = (proc.stderr or "").strip()[-500:]

    if payload is None:
        hint = stderr_tail or (proc.stdout or "").strip()[-500:] or "browser-use CLI 无 JSON 输出"
        if "remote-debugging" in hint.lower():
            hint = (
                "Chrome 需开启远程调试：在 chrome://inspect/#remote-debugging 勾选 "
                "'Allow remote debugging for this browser instance' 后重跑 forecast"
            )
        browser_login.update(skipped=False, success=False, reason="cli_parse_error", message=hint)
        return {
            "skipped": False,
            "success": False,
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
            "browser_login": browser_login,
            "message": hint,
            "job": "xueqiu_cookie_refresh",
        }

    cookies = payload.get("cookies") or []
    cookie_str = _cdp_cookies_to_header(cookies)
    token_seen = bool(payload.get("has_xq_a_token")) or _has_xq_a_token(cookie_str)
    browser_login["token_seen_in_browser"] = token_seen
    browser_login["page_url"] = payload.get("url") or url

    if not token_seen:
        browser_login.update(
            skipped=False,
            success=False,
            reason="timeout",
            message=(
                f"{BROWSER_USE_ENGINE} 已打开 {url}，但在 {timeout_sec}s 内未检测到 xq_a_token；"
                "请在 Chrome 窗口登录后重跑 forecast"
            ),
        )
        return {
            "skipped": False,
            "success": False,
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
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
        message=f"{BROWSER_USE_ENGINE} 检测到 xq_a_token（等待 {waited_sec}s）",
    )
    return {
        "skipped": False,
        "success": True,
        "engine": BROWSER_USE_ENGINE,
        "repo": repo,
        "browser_login": browser_login,
        "message": f"{n_cookies} cookies (含 xq_a_token，{BROWSER_USE_ENGINE}/CDP)",
        "job": "xueqiu_cookie_refresh",
    }


async def _async_refresh_xueqiu_cookie_library(
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
    repo = _browser_use_repo(settings)
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
        "engine": BROWSER_USE_ENGINE,
        "repo": repo,
        "method": "browser-use-library",
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
                    f"{BROWSER_USE_ENGINE} 已打开 {url}，但在 {timeout_sec}s 内未检测到 xq_a_token；"
                    "请在 Chrome 窗口登录后重跑 forecast"
                ),
            )
            return {
                "skipped": False,
                "success": False,
                "engine": BROWSER_USE_ENGINE,
                "repo": repo,
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
            message=f"{BROWSER_USE_ENGINE} 检测到 xq_a_token（等待 {waited_sec}s）",
        )
        return {
            "skipped": False,
            "success": True,
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
            "browser_login": browser_login,
            "message": f"{n_cookies} cookies (含 xq_a_token，{BROWSER_USE_ENGINE}/CDP)",
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
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
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
    """Sync wrapper: browser-use CLI first, Python library fallback."""
    repo = _browser_use_repo(settings)
    cli_result: dict[str, Any] | None = None
    if not browser_use_available():
        return {
            "skipped": True,
            "success": False,
            "reason": "browser_use_not_installed",
            "message": (
                f"未安装 {repo}，请执行："
                f"pip install git+https://github.com/{BROWSER_USE_REPO}.git"
            ),
            "job": "xueqiu_cookie_refresh",
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
        }

    if browser_use_cli_available():
        cli_result = _refresh_via_browser_use_cli(settings=settings, config=config)
        if cli_result.get("success") or cli_result.get("skipped"):
            return cli_result

    try:
        import browser_use  # noqa: F401
    except ImportError:
        return cli_result if cli_result is not None else {
            "skipped": True,
            "success": False,
            "reason": "browser_use_not_installed",
            "message": (
                f"未安装 {repo}，请执行："
                f"pip install git+https://github.com/{BROWSER_USE_REPO}.git"
            ),
            "job": "xueqiu_cookie_refresh",
            "engine": BROWSER_USE_ENGINE,
            "repo": repo,
        }

    return asyncio.run(_async_refresh_xueqiu_cookie_library(settings=settings, config=config))
