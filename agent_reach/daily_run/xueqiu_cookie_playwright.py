# -*- coding: utf-8
"""Xueqiu cookie refresh via Playwright headed login (ticket-sniper pattern)."""

from __future__ import annotations

import json
import sys
import threading
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
DEFAULT_SESSION_FILE = Path.home() / ".agent-reach" / "xueqiu_session.json"

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


def session_file_path(settings: Optional[dict[str, Any]] = None) -> Path:
    wf = _week_forecast_settings(settings)
    raw = str(wf.get("xueqiu_cookie_playwright_session_file") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_SESSION_FILE


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


def _playwright_chromium_installed(playwright: Any) -> bool:
    try:
        exe = playwright.chromium.executable_path
        return bool(exe and Path(str(exe)).exists())
    except Exception:
        return False


def _launch_persistent_context(playwright: Any, *, profile_dir: Path, headed: bool) -> Any:
    """
    Launch Chrome persistent context; fall back like ticket-sniper ``lib/browser.mjs``.

    Order: Playwright Chromium (if installed) → system Chrome channel → explicit path.
    """
    opts: dict[str, Any] = {
        "headless": not headed,
        "args": list(_LAUNCH_ARGS),
        "viewport": {"width": 1280, "height": 800},
        "user_agent": _USER_AGENT,
    }
    user_data_dir = str(profile_dir)
    errors: list[str] = []

    if _playwright_chromium_installed(playwright):
        try:
            return playwright.chromium.launch_persistent_context(user_data_dir, **opts)
        except Exception as exc:
            errors.append(f"chromium: {exc}")

    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            **opts,
        )
    except Exception as exc:
        errors.append(f"channel=chrome: {exc}")

    chrome_bin = _find_chrome_binary()
    if chrome_bin:
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir,
                executable_path=chrome_bin,
                **opts,
            )
        except Exception as exc:
            errors.append(f"executable_path: {exc}")

    hint = (
        "无法启动 Playwright 浏览器。请运行: python3 -m playwright install chromium "
        "或安装 Google Chrome。"
    )
    if errors:
        hint = f"{hint} ({errors[-1][:160]})"
    raise RuntimeError(hint)


def _save_session_file(cookies: list[Any], settings: Optional[dict[str, Any]] = None) -> Path:
    path = session_file_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for raw in cookies or []:
        if isinstance(raw, dict):
            serializable.append(raw)
        else:
            serializable.append(
                {
                    "name": getattr(raw, "name", ""),
                    "value": getattr(raw, "value", ""),
                    "domain": getattr(raw, "domain", ""),
                    "path": getattr(raw, "path", "/"),
                }
            )
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _load_session_file(settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    path = session_file_path(settings)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _persist_cookie_string(cookie_str: str, *, config=None) -> None:
    from agent_reach.config import Config

    cfg = config or Config()
    cfg.set("xueqiu_cookie", cookie_str)
    cfg.save()
    _reset_xueqiu_channel_cookies()


def _success_result(
    *,
    cookie_str: str,
    browser_login: dict[str, Any],
    method: str,
    waited_sec: int = 0,
) -> dict[str, Any]:
    n_cookies = len([p for p in cookie_str.split(";") if p.strip()])
    browser_login.update(
        skipped=False,
        success=True,
        reason="token_ready",
        method=method,
        waited_sec=waited_sec,
        token_seen_in_browser=True,
        message=f"{PLAYWRIGHT_ENGINE} 检测到 xq_a_token（{method}）",
    )
    return {
        "skipped": False,
        "success": True,
        "engine": PLAYWRIGHT_ENGINE,
        "browser_login": browser_login,
        "message": f"{n_cookies} cookies (含 xq_a_token，{PLAYWRIGHT_ENGINE}/{method})",
        "job": "xueqiu_cookie_refresh",
    }


def refresh_xueqiu_cookie_from_session_file(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """Load cookies from ticket-sniper-style session JSON (no browser launch)."""
    cookies = _load_session_file(settings)
    cookie_str = _cookies_to_header(cookies)
    browser_login: dict[str, Any] = {
        "job": "xueqiu_cookie_browser_login",
        "engine": PLAYWRIGHT_ENGINE,
        "method": "session-file",
        "session_file": str(session_file_path(settings)),
        "token_seen_in_browser": _has_xq_a_token(cookie_str),
    }
    if not _has_xq_a_token(cookie_str):
        return {
            "skipped": True,
            "success": False,
            "reason": "session_missing_token",
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": f"session 文件无 xq_a_token: {session_file_path(settings)}",
            "job": "xueqiu_cookie_refresh",
        }
    _persist_cookie_string(cookie_str, config=config)
    return _success_result(
        cookie_str=cookie_str,
        browser_login=browser_login,
        method="session-file",
    )


def refresh_xueqiu_cookie_from_profile_headless(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """Read cookies from Playwright persistent profile without headed login (cron-safe)."""
    if not playwright_available():
        return {
            "skipped": True,
            "success": False,
            "reason": "playwright_not_installed",
            "engine": PLAYWRIGHT_ENGINE,
            "job": "xueqiu_cookie_refresh",
        }

    profile_dir = _profile_dir(settings)
    browser_login: dict[str, Any] = {
        "job": "xueqiu_cookie_browser_login",
        "engine": PLAYWRIGHT_ENGINE,
        "method": "playwright-profile-headless",
        "profile_dir": str(profile_dir),
        "token_seen_in_browser": False,
    }
    if not profile_dir.is_dir():
        return {
            "skipped": True,
            "success": False,
            "reason": "profile_missing",
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": f"Playwright profile 不存在: {profile_dir}",
            "job": "xueqiu_cookie_refresh",
        }

    from playwright.sync_api import sync_playwright

    cookie_str = ""
    cookies_raw: list[Any] = []
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = _launch_persistent_context(
                playwright,
                profile_dir=profile_dir,
                headed=False,
            )
            try:
                cookies_raw = context.cookies()
                cookie_str = _cookies_to_header(cookies_raw)
            finally:
                context.close()
    except Exception as exc:
        browser_login.update(success=False, reason="playwright_error", message=str(exc))
        return {
            "skipped": False,
            "success": False,
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": str(exc),
            "job": "xueqiu_cookie_refresh",
        }

    if not _has_xq_a_token(cookie_str):
        return {
            "skipped": True,
            "success": False,
            "reason": "profile_missing_token",
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": "Playwright profile 中无 xq_a_token，需 headed 登录",
            "job": "xueqiu_cookie_refresh",
        }

    if cookies_raw:
        _save_session_file(cookies_raw, settings=settings)
    _persist_cookie_string(cookie_str, config=config)
    return _success_result(
        cookie_str=cookie_str,
        browser_login=browser_login,
        method="playwright-profile-headless",
    )


def refresh_xueqiu_cookie_via_playwright(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
    interactive: bool = False,
) -> dict[str, Any]:
    """
    Open a headed browser on the Xueqiu login page, wait for xq_a_token, persist cookies.

    Mirrors zjk1984/ticket-sniper ``scripts/login.mjs``: persistent profile, login URL,
    poll until session cookies appear (or Enter on TTY when ``interactive``), then save.
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
            "message": "未安装 playwright，请 pip install 'agent-reach[daily-run]' 后运行 playwright install chromium",
            "job": "xueqiu_cookie_refresh",
        }

    if headed and not _has_gui_display():
        return {
            "skipped": True,
            "success": False,
            "reason": "no_display",
            "engine": PLAYWRIGHT_ENGINE,
            "browser_login": browser_login,
            "message": "无 DISPLAY/WAYLAND，请运行: python3 -m agent_reach.cli daily-run xueqiu login",
            "job": "xueqiu_cookie_refresh",
        }

    profile_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    token_seen = False
    cookie_str = ""
    cookies_raw: list[Any] = []
    started = time.monotonic()
    enter_pressed = threading.Event()

    def _wait_enter() -> None:
        if interactive and sys.stdin.isatty():
            try:
                input()
                enter_pressed.set()
            except EOFError:
                pass

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

                if interactive and sys.stdin.isatty():
                    print("🍪 雪球登录（Playwright / ticket-sniper 模式）")
                    print("=" * 40)
                    print(f"已在浏览器打开: {url}")
                    print("请在浏览器中完成登录，完成后回到此终端按 Enter …")
                    threading.Thread(target=_wait_enter, daemon=True).start()

                while time.monotonic() - started < timeout_sec:
                    cookies_raw = context.cookies()
                    cookie_str = _cookies_to_header(cookies_raw)
                    if _has_xq_a_token(cookie_str):
                        token_seen = True
                        time.sleep(min(3, poll_sec))
                        cookies_raw = context.cookies()
                        cookie_str = _cookies_to_header(cookies_raw)
                        break
                    if interactive and enter_pressed.is_set():
                        cookies_raw = context.cookies()
                        cookie_str = _cookies_to_header(cookies_raw)
                        if _has_xq_a_token(cookie_str):
                            token_seen = True
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
                "请在浏览器窗口完成登录后重试"
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

    _save_session_file(cookies_raw, settings=settings)
    _persist_cookie_string(cookie_str, config=config)

    return _success_result(
        cookie_str=cookie_str,
        browser_login=browser_login,
        method="playwright-persistent",
        waited_sec=waited_sec,
    )


def run_xueqiu_interactive_login(
    *,
    settings: Optional[dict[str, Any]] = None,
    config=None,
) -> dict[str, Any]:
    """CLI entry: ticket-sniper style headed login with Enter-to-save."""
    return refresh_xueqiu_cookie_via_playwright(
        settings=settings,
        config=config,
        interactive=True,
    )
