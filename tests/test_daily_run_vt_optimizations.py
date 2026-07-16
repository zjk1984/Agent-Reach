# -*- coding: utf-8
"""Tests for Vibe-Trading-inspired daily-run optimizations."""

from unittest.mock import patch

from datetime import datetime, timezone

import pytest

from agent_reach.daily_run.auditor import run_data_audit
from agent_reach.daily_run.job_health import record_job_outcome
from agent_reach.daily_run.quote_fetch import QuoteFetchResult, normalize_code
from agent_reach.daily_run.retry_utils import retry_with_backoff
from agent_reach.daily_run.settings import load_settings, validate_settings
from agent_reach.integrations.feishu import FeishuError, _send_with_retry


class TestRetryUtils:
    def test_retry_succeeds_first_try(self):
        assert retry_with_backoff(lambda: 42, max_retries=2) == 42

    def test_retry_then_succeed(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return "ok"

        assert retry_with_backoff(fn, max_retries=3, backoff=(0, 0)) == "ok"


class TestQuoteFetch:
    def test_normalize_code(self):
        assert normalize_code("688008") == "688008"
        assert normalize_code("1") == "000001"

    def test_coverage_for(self):
        r = QuoteFetchResult(quotes={"688008": {"code": "688008", "price": 1.0}})
        assert r.coverage_for(["688008", "000001"]) == 0.5


class TestAuditorCoverage:
    def test_low_quote_coverage_blocks(self):
        settings = {
            **load_settings(),
            "data_audit": {
                **load_settings().get("data_audit", {}),
                "quote_coverage_mode": "block",
                "min_quote_coverage_pct": 0.8,
            },
        }
        snap = {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "code": "688008",
            "name": "测试",
            "price": 10,
            "reference_price": 10,
            "sources": {
                "quote": {"summary": "ok"},
                "flow": {"summary": "ok"},
                "sentiment": {"summary": "ok"},
            },
            "quote_fetch": {"coverage_pct": 50.0, "errors": {"000001": "missing"}},
        }
        result = run_data_audit(snap, settings)
        assert result.passed is False
        assert any("覆盖率" in i for i in result.issues)


class TestSettingsValidation:
    def test_validate_settings_ok(self):
        validate_settings(load_settings())

    def test_validate_settings_bad_thresholds(self):
        data = load_settings()
        data["thresholds"] = {}
        with pytest.raises(ValueError, match="thresholds"):
            validate_settings(data)


class TestFeishuRetry:
    def test_send_with_retry(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise FeishuError("rate limit")
            return {"code": 0}

        out = _send_with_retry(fn, max_retries=3, backoff=(0, 0))
        assert out["code"] == 0
        assert calls["n"] == 2


class TestJobHealth:
    def test_record_outcome(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agent_reach.daily_run.job_health.health_path",
            lambda: tmp_path / "job_health.json",
        )
        streak = record_job_outcome("morning", success=False, error="test")
        assert streak == 1
        streak = record_job_outcome("morning", success=False, error="test2")
        assert streak == 2
        record_job_outcome("morning", success=True)
        streak = record_job_outcome("morning", success=False, error="again")
        assert streak == 1
