# -*- coding: utf-8
"""Tests for 60s web portal."""

from agent_reach.daily_run.hot_news_portal import PORTAL_PORT, _portal_html


def test_portal_html_contains_dashboard():
    html = _portal_html("http://127.0.0.1:8787")
    assert "60s 热点新闻面板" in html
    assert str(PORTAL_PORT) in html
    assert "/v2/60s?encoding=json" in html
