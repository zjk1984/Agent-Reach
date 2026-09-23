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
    refresh_xueqiu_cookie_from_profile_headless,
    refresh_xueqiu_cookie_from_session_file,
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


def test_refresh_from_session_file_success():
    mock_cfg = MagicMock()
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._load_session_file",
        return_value=[{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
    ), patch("agent_reach.config.Config", return_value=mock_cfg), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._reset_xueqiu_channel_cookies"
    ):
        result = refresh_xueqiu_cookie_from_session_file(settings={"week_forecast": {}})
    assert result["success"] is True
    assert result["browser_login"]["method"] == "session-file"
    mock_cfg.set.assert_called_once()
    mock_cfg.save.assert_called_once()


def test_refresh_from_session_file_missing_token():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._load_session_file",
        return_value=[{"name": "u", "value": "1", "domain": ".xueqiu.com"}],
    ):
        result = refresh_xueqiu_cookie_from_session_file(settings={"week_forecast": {}})
    assert result["skipped"] is True
    assert result["reason"] == "session_missing_token"


def test_refresh_profile_headless_saves_session_once(tmp_path):
    profile = tmp_path / "xq-profile"
    profile.mkdir()
    mock_cfg = MagicMock()
    mock_context = MagicMock()
    mock_context.cookies.return_value = [
        {"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"},
    ]
    mock_playwright = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_playwright
    mock_cm.__exit__.return_value = None
    mock_sync_api = MagicMock()
    mock_sync_api.sync_playwright.return_value = mock_cm
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._profile_dir",
        return_value=profile,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._launch_persistent_context",
        return_value=mock_context,
    ) as mock_launch, patch.dict(
        sys.modules,
        {"playwright": MagicMock(), "playwright.sync_api": mock_sync_api},
    ), patch("agent_reach.config.Config", return_value=mock_cfg), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._reset_xueqiu_channel_cookies"
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright._save_session_file"
    ) as mock_save:
        result = refresh_xueqiu_cookie_from_profile_headless(settings={"week_forecast": {}})
    assert result["success"] is True
    mock_launch.assert_called_once()
    mock_save.assert_called_once()
    mock_context.close.assert_called_once()


def test_refresh_prefers_session_file_over_browser_use():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_session_file",
        return_value={"success": True, "engine": PLAYWRIGHT_ENGINE, "job": "xueqiu_cookie_refresh"},
    ) as mock_session, patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_profile_headless",
    ) as mock_profile, patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_via_playwright",
    ) as mock_pw, patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
    ) as mock_bu:
        out = refresh_xueqiu_cookie_from_browser(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_use_playwright": True,
                    "xueqiu_cookie_use_browser_use": True,
                    "xueqiu_cookie_refresh_every_forecast": False,
                }
            }
        )
    mock_session.assert_called_once()
    mock_profile.assert_not_called()
    mock_pw.assert_not_called()
    mock_bu.assert_not_called()
    assert out["engine"] == PLAYWRIGHT_ENGINE


def test_refresh_every_forecast_skips_session_for_headed_playwright():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_session_file",
    ) as mock_session, patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_profile_headless",
    ) as mock_profile, patch(
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
                    "xueqiu_cookie_refresh_every_forecast": True,
                }
            }
        )
    mock_session.assert_not_called()
    mock_profile.assert_not_called()
    mock_pw.assert_called_once()
    mock_bu.assert_not_called()
    assert out["engine"] == PLAYWRIGHT_ENGINE


def test_refresh_playwright_timeout_skips_browser_use():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_session_file",
        return_value={"skipped": True, "success": False, "reason": "session_missing_token"},
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_profile_headless",
        return_value={"skipped": True, "success": False, "reason": "profile_missing_token"},
    ), patch(
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
                    "xueqiu_cookie_refresh_every_forecast": False,
                }
            }
        )
    mock_bu.assert_not_called()
    assert out["reason"] == "timeout"


def test_refresh_no_display_does_not_fall_through_to_browser_use():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_session_file",
        return_value={"skipped": True, "success": False, "reason": "session_missing_token"},
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_from_profile_headless",
        return_value={"skipped": True, "success": False, "reason": "profile_missing_token"},
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.playwright_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_playwright.refresh_xueqiu_cookie_via_playwright",
        return_value={
            "skipped": True,
            "success": False,
            "reason": "no_display",
            "engine": PLAYWRIGHT_ENGINE,
            "job": "xueqiu_cookie_refresh",
        },
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
    ) as mock_bu, patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
    ) as mock_chrome:
        out = refresh_xueqiu_cookie_from_browser(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_use_playwright": True,
                    "xueqiu_cookie_use_browser_use": True,
                    "xueqiu_cookie_refresh_every_forecast": False,
                }
            }
        )
    mock_bu.assert_not_called()
    mock_chrome.assert_not_called()
    assert out["reason"] == "no_display"
    assert "daily-run xueqiu login" in out["message"]
