# -*- coding: utf-8
"""Bounded JSONL append helper — caps unbounded harness audit/diff log growth."""

import json

from agent_reach.daily_run.jsonl_log import append_jsonl_capped


def test_append_writes_line(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl_capped(path, {"a": 1})
    append_jsonl_capped(path, {"a": 2})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"a": 2}


def test_no_truncation_below_size_threshold(tmp_path):
    path = tmp_path / "log.jsonl"
    for i in range(50):
        append_jsonl_capped(path, {"i": i}, max_lines=10, check_every_bytes=10_000_000)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50


def test_truncates_to_max_lines_once_size_threshold_crossed(tmp_path):
    path = tmp_path / "log.jsonl"
    # Force truncation to kick in immediately (check_every_bytes=0) so we can
    # assert the file never grows past max_lines regardless of append count.
    for i in range(500):
        append_jsonl_capped(path, {"i": i}, max_lines=20, check_every_bytes=0)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    # Most recent records survive; oldest are dropped.
    assert json.loads(lines[-1]) == {"i": 499}
    assert json.loads(lines[0]) == {"i": 480}


def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "log.jsonl"
    append_jsonl_capped(path, {"ok": True})
    assert path.exists()
