# -*- coding: utf-8
"""CSI300 week macro band — asymmetric downside widen via forecast_miss_overlay."""

from __future__ import annotations

from unittest.mock import patch

from agent_reach.daily_run.forecast_miss_overlay import (
    apply_forecast_miss_overlay,
    macro_downside_band_extra,
)
from agent_reach.daily_run.forecast_quality import enrich_market_prediction
from agent_reach.daily_run.forecast_structured import build_market_prediction


def test_build_market_prediction_widens_downside_only():
  settings = {"week_forecast": {"macro_downside_extra_pct": 0.6, "macro_downside_band": True}}
  with patch(
      "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
      return_value=0,
  ):
      pred = build_market_prediction(
          mss_daily={
              "2026-11-10": {"median": 52.0, "range": [50, 54]},
              "2026-11-14": {"median": 52.0, "range": [50, 54]},
          },
          calibration={"bias_pct": 0.0, "vol_scale": 1.0},
          settings=settings,
      )
  base_lo = -1.0
  assert pred["change_pct_high"] == 1.0
  assert pred["change_pct_low"] == round(base_lo - 0.6, 2)
  assert pred["macro_downside_extra_pct"] == 0.6


def test_macro_downside_extra_grows_with_miss_streak():
  settings = {
      "week_forecast": {
          "macro_downside_extra_pct": 0.6,
          "macro_downside_streak_step_pct": 0.15,
          "macro_downside_max_extra_pct": 1.2,
          "macro_downside_min_streak": 2,
          "miss_streak_min_days": 2,
      }
  }
  with patch(
      "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
      return_value=3,
  ):
      extra = macro_downside_band_extra(settings)
  assert extra == round(0.6 + 0.15 * 3, 2)


def test_enrich_market_keeps_build_downside_pad():
  settings = {"week_forecast": {"macro_downside_extra_pct": 0.6}}
  with patch(
      "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
      return_value=0,
  ):
      raw = build_market_prediction(
          mss_daily={
              "2026-11-10": {"median": 52.0},
              "2026-11-14": {"median": 52.0},
          },
          calibration={"bias_pct": 0.0, "vol_scale": 1.0},
          settings=settings,
      )
      pred = enrich_market_prediction(raw, calibration={"hit_rate": 0.75})
  assert pred["change_pct_low"] == raw["change_pct_low"]
  assert pred["change_pct_high"] == raw["change_pct_high"]
  assert pred.get("macro_downside_extra_pct") == 0.6


def test_forecast_miss_overlay_records_macro_downside(monkeypatch):
  monkeypatch.setattr(
      "agent_reach.daily_run.forecast_miss_overlay.forecast_mss_miss_streak",
      lambda **k: 2,
  )
  monkeypatch.setattr(
      "agent_reach.daily_run.forecast_miss_overlay.forecast_miss_cfg",
      lambda s: {
          "enabled": True,
          "min_miss_streak": 2,
          "base_spread_delta": 2,
          "max_base_spread": 14,
      },
  )
  monkeypatch.setattr(
      "agent_reach.daily_run.harness_policy.forecast_int_default",
      lambda settings, key: 8,
  )
  out = apply_forecast_miss_overlay({"mss_forecast": {"base_spread": 8}})
  fm = (out.get("harness_runtime") or {}).get("forecast_miss") or {}
  assert fm.get("macro_downside_extra_pct", 0) > 0