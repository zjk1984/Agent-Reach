# -*- coding: utf-8
"""Tests for browser-use Xueqiu cookie refresh."""

from unittest.mock import AsyncMock, MagicMock, patch

from agent_reach.daily_run.xueqiu_cookie_browser_use import (
    BROWSER_USE_ENGINE,
    BROWSER_USE_REPO,
    _cdp_cookies_to_header,
    _parse_cli_json,
    browser_use_available,
    browser_use_cli_path,
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


def test_parse_cli_json_last_line():
    payload = _parse_cli_json("log\n{\"has_xq_a_token\": true, \"cookies\": []}\n")
    assert payload["has_xq_a_token"] is True


def test_render_refresh_markdown_success():
    md = render_xueqiu_cookie_refresh_markdown(
        {
            "success": True,
            "engine": BROWSER_USE_ENGINE,
            "repo": f"https://github.com/{BROWSER_USE_REPO}",
            "message": f"18 cookies (含 xq_a_token，{BROWSER_USE_ENGINE}/CDP)",
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
    assert BROWSER_USE_ENGINE in md
    assert BROWSER_USE_REPO in md
    assert "刷新后探针" in md


def test_refresh_via_browser_use_not_installed():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=False,
    ):
        result = refresh_xueqiu_cookie_via_browser_use(settings={"week_forecast": {}})
    assert result["skipped"] is True
    assert result["reason"] == "browser_use_not_installed"
    assert BROWSER_USE_REPO in result["message"]


def test_refresh_via_browser_use_cli_success():
    mock_cfg = MagicMock()
    stdout = '{"has_xq_a_token": true, "cookies": [{"name":"xq_a_token","value":"tok","domain":".xueqiu.com"}], "url":"https://xueqiu.com/"}\n'
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_cli_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.subprocess.run",
        return_value=MagicMock(stdout=stdout, stderr="", returncode=0),
    ), patch("agent_reach.config.Config", return_value=mock_cfg), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use._reset_xueqiu_channel_cookies"
    ):
        result = refresh_xueqiu_cookie_via_browser_use(settings={"week_forecast": {}})

    assert result["success"] is True
    assert result["engine"] == BROWSER_USE_ENGINE
    assert result["browser_login"]["method"] == "browser-use-cli"
    mock_cfg.set.assert_called_once()
    mock_cfg.save.assert_called_once()


def test_refresh_via_browser_use_library_fallback():
    mock_browser = MagicMock()
    mock_browser.start = AsyncMock()
    mock_browser.stop = AsyncMock()
    mock_browser.navigate_to = AsyncMock()
    mock_browser.cookies = AsyncMock(
        side_effect=[
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
        ]
    )
    mock_cfg = MagicMock()
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_cli_available",
        return_value=False,
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
    assert result["browser_login"]["method"] == "browser-use-library"


def test_refresh_prefers_browser_use_when_enabled():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.refresh_xueqiu_cookie_via_browser_use",
        return_value={"success": True, "engine": BROWSER_USE_ENGINE, "job": "xueqiu_cookie_refresh"},
    ) as mock_bu, patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
    ) as mock_legacy:
        from agent_reach.daily_run.xueqiu_cookie_health import refresh_xueqiu_cookie_from_browser

        out = refresh_xueqiu_cookie_from_browser(
            settings={"week_forecast": {"xueqiu_cookie_use_browser_use": True}}
        )
    mock_bu.assert_called_once()
    mock_legacy.assert_not_called()
    assert out["engine"] == BROWSER_USE_ENGINE


def test_browser_use_cli_path_checks_user_local_bin():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use._user_local_bin",
        return_value="/home/zjk/.local/bin/browser-use",
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.shutil.which",
        return_value=None,
    ):
        assert browser_use_cli_path() == "/home/zjk/.local/bin/browser-use"


def test_refresh_cli_failure_falls_back_to_library():
    mock_browser = MagicMock()
    mock_browser.start = AsyncMock()
    mock_browser.stop = AsyncMock()
    mock_browser.navigate_to = AsyncMock()
    mock_browser.cookies = AsyncMock(
        side_effect=[
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
            [{"name": "xq_a_token", "value": "tok", "domain": ".xueqiu.com"}],
        ]
    )
    mock_cfg = MagicMock()
    cli_fail = {
        "skipped": False,
        "success": False,
        "engine": BROWSER_USE_ENGINE,
        "message": "cli parse error",
        "job": "xueqiu_cookie_refresh",
    }
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_cli_available",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use._refresh_via_browser_use_cli",
        return_value=cli_fail,
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
    assert result["browser_login"]["method"] == "browser-use-library"


def test_browser_use_enabled_skips_legacy_when_unavailable():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_browser_use.browser_use_available",
        return_value=False,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
    ) as mock_legacy:
        from agent_reach.daily_run.xueqiu_cookie_health import refresh_xueqiu_cookie_from_browser

        out = refresh_xueqiu_cookie_from_browser(
            settings={"week_forecast": {"xueqiu_cookie_use_browser_use": True}}
        )
    mock_legacy.assert_not_called()
    assert out["skipped"] is True
    assert out["reason"] == "browser_use_not_installed"
    assert out["engine"] == BROWSER_USE_ENGINE
