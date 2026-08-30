# -*- coding: utf-8
"""Tests for browser-use Xueqiu cookie refresh."""

from unittest.mock import AsyncMock, MagicMock, patch

from agent_reach.daily_run.xueqiu_cookie_browser_use import (
    _cdp_cookies_to_header,
    browser_use_available,
    refresh_xueqiu_cookie_via_browser_use,
)
from agent_reach.daily_run.xueqiu_cookie_health import render_xueqiu_cookie_refresh_markdown


def test_cdp_cookies_to_header_filters_xueqiu():
    header = _cdp_cookies_to_header(
        [
            {"name": "xq_a_token", "value": "abc", "domain": ".xueqiu.com"},
            {"name": "u", "value": "1", "domain": "xueqiu.com"},
            {"name": "other", "value": "x", "domain": ".google.com"},
        ]
    )
    assert "xq_a_token=abc" in header
    assert "other=x" not in header


def test_render_refresh_markdown_success():
    md = render_xueqiu_cookie_refresh_markdown(
        {
            "success": True,
            "engine": "browser-use",
            "message": "18 cookies (含 xq_a_token，browser-use/CDP)",
            "browser_login": {
                "url": "https://xueqiu.com",
                "profile": "Default",
                "waited_sec": 12,
            },
        },
        health={"status": "ok", "message": "雪球 Cookie 有效"},
    )
    assert "雪球 Cookie 更新" in md
    assert "✅ 成功" in md
    assert "browser-use" in md
    assert "刷新后探针" in md


def test_render_refresh_markdown_failure():
    md = render_xueqiu_cookie_refresh_markdown(
        {"success": False, "engine": "browser-use", "message": "timeout"},
    )
    assert "❌ 失败" in md


def test_refresh_via_browser_use_not_installed():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=False,
    ):
        result = refresh_xueqiu_cookie_via_browser_use(settings={"week_forecast": {}})
    assert result["skipped"] is True
    assert result["reason"] == "browser_use_not_installed"


def test_refresh_via_browser_use_success():
    mock_browser = MagicMock()
    mock_browser.start = AsyncMock()
    mock_browser.stop = AsyncMock()
    mock_browser.navigate_to = AsyncMock()
    mock_browser.cookies = AsyncMock(
        side_effect=[
            [{"name": "u", "value": "1", "domain": ".xueqiu.com"}],
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
        ]
    )

    mock_cfg = MagicMock()
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "browser_use.Browser.from_system_chrome",
        return_value=mock_browser,
    ), patch("agent_reach.config.Config", return_value=mock_cfg), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use._reset_xueqiu_channel_cookies"
    ):
        result = refresh_xueqiu_cookie_via_browser_use(settings={"week_forecast": {}})

    assert result["success"] is True
    assert result["engine"] == "browser-use"
    mock_cfg.set.assert_called_once()
    mock_cfg.save.assert_called_once()


def test_refresh_prefers_browser_use_when_enabled():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
        return_value={"success": True, "engine": "browser-use", "job": "xueqiu_cookie_refresh"},
    ) as mock_bu:
        from agent_reach.daily_run.xueqiu_cookie_health import refresh_xueqiu_cookie_from_browser

        out = refresh_xueqiu_cookie_from_browser(
            settings={"week_forecast": {"xueqiu_cookie_use_browser_use": True}}
        )
    mock_bu.assert_called_once()
    assert out["engine"] == "browser-use"
