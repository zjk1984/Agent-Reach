# -*- coding: utf-8
"""Tests for Playwright Xueqiu cookie refresh (ticket-sniper pattern)."""

import sys
from unittest.mock import MagicMock, patch

from agent_reach.daily_run.xueqiu_cookie_health import refresh_xueqiu_cookie_from_browser
from agent_reach.daily_run.xueqiu_cookie_playwright import (
    DEFAULT_LOGIN_URL,
    PLAYWRIGHT_ENGINE,
    _cookies_to_header,
    playwright_available,
    refresh_xueqiu_cookie_via_playwright,
)


def test_cookies_to_header_filters_xueqiu():
    header = _cookies_to_header(
        [
            {"name": "xq_a_token", "value": "abc", "domain": ".xueqiu.com"},
            {"name": "other", "value": "x", "domain": ".google.com"},
        ]
    )
    assert "xq_a_token=abc" in header
    assert "other=x" not in header


def test_default_login_url_is_login_page():
    assert DEFAULT_LOGIN_URL == "https://xueqiu.com/user/login"


def test_refresh_via_playwright_not_installed():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=False,
    ):
        result = refresh_xueqiu_cookie_via_playwright(settings={"week_forecast": {}})
    assert result["skipped"] is True
    assert result["reason"] == "playwright_not_installed"


def test_refresh_via_playwright_success():
    mock_cfg = MagicMock()
    mock_page = MagicMock()
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    mock_context.cookies.side_effect = [
        [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
        [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
    ]
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch_persistent_context.return_value = mock_context
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_playwright
    mock_cm.__exit__.return_value = None

    mock_sync_api = MagicMock()
    mock_sync_api.sync_playwright.return_value = mock_cm
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._has_gui_display",
        return_value=True,
    ), patch.dict(
        sys.modules,
        {"playwright": MagicMock(), "playwright.sync_api": mock_sync_api},
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._launch_persistent_context",
        return_value=mock_context,
    ), patch("agent_reach.config.Config", return_value=mock_cfg), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._reset_xueqiu_channel_cookies"
    ):
        result = refresh_xueqiu_cookie_via_playwright(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_browser_login_url": "https://xueqiu.com/user/login",
                    "xueqiu_cookie_browser_login_timeout_sec": 10,
                }
            }
        )

    assert result["success"] is True
    assert result["engine"] == PLAYWRIGHT_ENGINE
    assert result["browser_login"]["method"] == "playwright-persistent"
    assert result["browser_login"]["url"] == "https://xueqiu.com/user/login"
    mock_page.goto.assert_called_once()
    mock_cfg.set.assert_called_once()
    mock_cfg.save.assert_called_once()


def test_refresh_prefers_playwright_over_browser_use():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_via_playwright",
        return_value={"success": True, "engine": PLAYWRIGHT_ENGINE, "job": "xueqiu_cookie_refresh"},
    ) as mock_pw, patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
    ) as mock_bu:
        out = refresh_xueqiu_cookie_from_browser(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_use_playwright": True,
                    "xueqiu_cookie_use_browser_use": True,
                }
            }
        )
    mock_pw.assert_called_once()
    mock_bu.assert_not_called()
    assert out["engine"] == PLAYWRIGHT_ENGINE


def test_refresh_playwright_timeout_skips_browser_use():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_via_playwright",
        return_value={
            "success": False,
            "reason": "timeout",
            "engine": PLAYWRIGHT_ENGINE,
            "job": "xueqiu_cookie_refresh",
        },
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
    ) as mock_bu:
        out = refresh_xueqiu_cookie_from_browser(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_use_playwright": True,
                    "xueqiu_cookie_use_browser_use": True,
                }
            }
        )
    mock_bu.assert_not_called()
    assert out["reason"] == "timeout"
