# -*- coding: utf-8
"""Tests for Xueqiu cookie health alerts in Sunday forecast."""

from unittest.mock import patch

from agent_reach.daily_run.week_forecast import render_forecast_sections
from agent_reach.daily_run.xueqiu_cookie_health import (
    check_xueqiu_cookie_health,
    ensure_xueqiu_browser_session,
    refresh_xueqiu_cookie_from_browser,
    render_xueqiu_cookie_alert_markdown,
)


def test_check_missing_cookie():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("", "none"),
    ), patch("agent_reach.channels.xueqiu.XueqiuChannel") as mock_cls:
        mock_cls.return_value.check.return_value = (
            "warn",
            "请先登录雪球后运行：agent-reach configure --from-browser chrome",
        )
        health = check_xueqiu_cookie_health()
    assert health["status"] == "missing"
    assert health["cookie_configured"] is False


def test_check_expired_cookie():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("u=1; acw_tc=abc", "config"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._probe_authenticated_api",
        return_value=(False, "401"),
    ), patch("agent_reach.channels.xueqiu.XueqiuChannel") as mock_cls:
        mock_cls.return_value.check.return_value = ("warn", "API 连接失败")
        health = check_xueqiu_cookie_health()
    assert health["status"] == "expired"
    assert health["has_xq_a_token"] is False


def test_check_expired_when_auth_probe_fails():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("xq_a_token=abc; u=1", "config"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._probe_authenticated_api",
        return_value=(False, "热股榜返回空列表"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_config_age_days",
        return_value=1,
    ):
        health = check_xueqiu_cookie_health()
    assert health["status"] == "expired"


def test_check_expiring_by_age():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("xq_a_token=abc; u=1", "config"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._probe_authenticated_api",
        return_value=(True, "热股榜接口正常"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_config_age_days",
        return_value=8,
    ):
        health = check_xueqiu_cookie_health(settings={"week_forecast": {"xueqiu_cookie_max_age_days": 7}})
    assert health["status"] == "expiring"
    assert "8 天" in health["message"]


def test_check_ok():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("xq_a_token=abc; u=1", "config"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._probe_authenticated_api",
        return_value=(True, "热股榜接口正常"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_config_age_days",
        return_value=2,
    ):
        health = check_xueqiu_cookie_health(
            macro_signals={"hot_stocks": [{"code": "600519"}]},
            live_macro_fetch=True,
        )
    assert health["status"] == "ok"


def test_check_degraded_when_live_fetch_failed():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_from_config",
        return_value=("xq_a_token=abc; u=1", "config"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._probe_authenticated_api",
        return_value=(True, "热股榜接口正常"),
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_config_age_days",
        return_value=2,
    ):
        health = check_xueqiu_cookie_health(
            macro_signals={"hot_stocks": [{"code": "600519"}]},
            live_macro_fetch=False,
        )
    assert health["status"] == "degraded"
    assert "回退周六缓存" in health["message"]


def test_render_alert_contains_cookie_steps():
    md = render_xueqiu_cookie_alert_markdown(
        {
            "status": "expired",
            "message": "雪球 Cookie 可能已过期或无效，请重新导出",
            "api_message": "401",
        }
    )
    assert "雪球 Cookie 预警" in md
    assert "Cookie-Editor" in md
    assert "xueqiu_cookie" in md
    assert "configure --from-browser chrome" in md


def test_render_alert_expiring_title():
    md = render_xueqiu_cookie_alert_markdown(
        {
            "status": "expiring",
            "message": "雪球 Cookie 已 8 天未更新",
            "cookie_age_days": 8,
        }
    )
    assert "即将到期" in md


def test_render_alert_empty_when_ok():
    assert render_xueqiu_cookie_alert_markdown({"status": "ok", "message": "ok"}) == ""


def test_forecast_sections_include_cookie_alert():
    sections = render_forecast_sections(
        {
            "week_start": "2026-07-13",
            "week_end": "2026-07-17",
            "mss_daily": {"2026-07-13": {"median": 52.0, "range": [50, 54]}},
            "symbols": {},
            "calibration_used": {"hit_rate": 0.5},
            "notes": [],
            "xueqiu_cookie_health": {
                "status": "expired",
                "message": "雪球 Cookie 可能已过期",
                "api_message": "fail",
            },
        }
    )
    assert sections[0].label == "上周验证"
    assert "Cookie-Editor" in sections[0].markdown


def test_refresh_skipped_when_disabled():
    result = refresh_xueqiu_cookie_from_browser(
        settings={"week_forecast": {"xueqiu_cookie_auto_refresh_from_browser": False}}
    )
    assert result["skipped"] is True


def test_refresh_success_resets_channel_cache():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
        return_value={"skipped": True, "success": True, "reason": "already_healthy"},
    ), patch("agent_reach.cookie_extract.configure_from_browser") as mock_cfg, patch(
        "agent_reach.daily_run.xueqiu_cookie_health._reset_xueqiu_channel_cookies"
    ) as mock_reset, patch("agent_reach.config.Config"):
        mock_cfg.return_value = [("Xueqiu", True, "18 cookies (含 xq_a_token)")]
        result = refresh_xueqiu_cookie_from_browser(settings={"week_forecast": {}})
    assert result["success"] is True
    assert result["browser"] == "chrome"
    mock_reset.assert_called_once()


def test_ensure_browser_login_skipped_when_disabled():
    result = ensure_xueqiu_browser_session(
        settings={"week_forecast": {"xueqiu_cookie_browser_login_enabled": False}}
    )
    assert result["skipped"] is True
    assert result["reason"] == "disabled"


def test_ensure_browser_login_skipped_when_healthy():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_needs_browser_login",
        return_value=False,
    ):
        result = ensure_xueqiu_browser_session(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_refresh_every_forecast": False,
                    "xueqiu_cookie_browser_login_skip_when_healthy": True,
                }
            }
        )
    assert result["skipped"] is True
    assert result["reason"] == "already_healthy"


def test_refresh_every_forecast_forces_browser_login_when_healthy():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health.check_xueqiu_cookie_health",
        return_value={"status": "ok"},
    ):
        assert (
            __import__(
                "agent_reach.daily_run.xueqiu_cookie_health",
                fromlist=["_cookie_needs_browser_login"],
            )._cookie_needs_browser_login(settings={"week_forecast": {}})
            is True
        )


def test_ensure_browser_login_skipped_without_display():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_needs_browser_login",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._has_gui_display",
        return_value=False,
    ):
        result = ensure_xueqiu_browser_session(settings={"week_forecast": {}})
    assert result["skipped"] is True
    assert result["reason"] == "no_display"


def test_ensure_browser_login_launches_chrome_and_waits_for_token():
    proc = type("P", (), {"pid": 4242, "poll": lambda self: None, "terminate": lambda self: None, "wait": lambda self, timeout=None: 0})()
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health._cookie_needs_browser_login",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._has_gui_display",
        return_value=True,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._find_chrome_binary",
        return_value="/usr/bin/google-chrome",
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health._is_chrome_running",
        return_value=False,
    ), patch(
        "agent_reach.daily_run.xueqiu_cookie_health.subprocess.Popen",
        return_value=proc,
    ) as mock_popen, patch(
        "agent_reach.daily_run.xueqiu_cookie_health._terminate_process_tree"
    ) as mock_kill, patch(
        "agent_reach.daily_run.xueqiu_cookie_health._browser_xueqiu_cookie_string",
        side_effect=["", "xq_a_token=abc; u=1"],
    ), patch("agent_reach.daily_run.xueqiu_cookie_health.time.sleep"):
        result = ensure_xueqiu_browser_session(
            settings={
                "week_forecast": {
                    "xueqiu_cookie_browser_login_timeout_sec": 30,
                    "xueqiu_cookie_browser_login_poll_sec": 1,
                }
            }
        )
    assert result["success"] is True
    assert result["token_seen_in_browser"] is True
    mock_popen.assert_called_once()
    mock_kill.assert_called_once_with(proc)


def test_refresh_still_extracts_when_chrome_running_with_token():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
        return_value={
            "skipped": False,
            "success": True,
            "reason": "chrome_running",
            "chrome_was_running": True,
            "token_seen_in_browser": True,
        },
    ), patch("agent_reach.cookie_extract.configure_from_browser") as mock_cfg, patch(
        "agent_reach.daily_run.xueqiu_cookie_health._reset_xueqiu_channel_cookies"
    ), patch("agent_reach.config.Config"):
        mock_cfg.return_value = [("Xueqiu", True, "17 cookies (含 xq_a_token)")]
        result = refresh_xueqiu_cookie_from_browser(settings={"week_forecast": {}})
    assert result["success"] is True
    mock_cfg.assert_called_once()


def test_refresh_calls_browser_login_before_extract():
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health.ensure_xueqiu_browser_session",
        return_value={"skipped": True, "success": True, "reason": "already_healthy"},
    ) as mock_ensure, patch("agent_reach.cookie_extract.configure_from_browser") as mock_cfg, patch(
        "agent_reach.daily_run.xueqiu_cookie_health._reset_xueqiu_channel_cookies"
    ), patch("agent_reach.config.Config"):
        mock_cfg.return_value = [("Xueqiu", True, "ok")]
        refresh_xueqiu_cookie_from_browser(settings={"week_forecast": {}})
    mock_ensure.assert_called_once()


def test_run_forecast_calls_cookie_refresh():
    from types import SimpleNamespace

    from agent_reach.daily_run.workflows import run_forecast

    snapshot = {"portfolio": {"holdings": [], "watchlist": []}}
    forecast_obj = SimpleNamespace(to_dict=lambda: {"week_start": "2026-08-24"})
    with patch(
        "agent_reach.daily_run.xueqiu_cookie_health.refresh_xueqiu_cookie_from_browser",
        return_value={"skipped": False, "success": True, "message": "ok"},
    ) as mock_refresh, patch(
        "agent_reach.daily_run.week_forecast.generate_week_forecast",
        return_value=forecast_obj,
    ), patch(
        "agent_reach.daily_run.week_forecast.persist_week_forecast",
        return_value=__import__("pathlib").Path("/tmp/f.json"),
    ), patch(
        "agent_reach.daily_run.week_forecast.render_forecast_markdown",
        return_value="md",
    ):
        out = run_forecast(snapshot, push=False, settings={"week_forecast": {"enabled": True}})
    mock_refresh.assert_called_once()
    assert "xueqiu_cookie_refresh" in out["steps"]
    assert out["xueqiu_cookie_refresh"]["success"] is True
