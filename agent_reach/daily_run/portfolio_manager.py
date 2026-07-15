# -*- coding: utf-8
"""Minimal trade ledger path helper for weekly report."""

from __future__ import annotations

from pathlib import Path


def default_ledger_path() -> Path:
    return Path.home() / ".agent-reach" / "daily_run" / "trade_ledger.jsonl"
