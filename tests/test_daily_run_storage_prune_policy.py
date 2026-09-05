# -*- coding: utf-8
"""Tests for storage prune policy helpers."""

from agent_reach.daily_run.storage.prune_policy import (
    PROTECTED_L0_KINDS,
    effective_prune_l0_kinds,
    effective_prune_l1_kinds,
)


def test_protected_l0_never_in_prune_list():
    kinds = effective_prune_l0_kinds()
    for protected in PROTECTED_L0_KINDS:
        assert protected not in kinds


def test_l1_prune_respects_disabled():
    assert effective_prune_l1_kinds(settings={"storage": {"prune": {"l1_prune_enabled": False}}}) == []


def test_run_distill_batches_unlimited(monkeypatch):
    from agent_reach.daily_run.storage.prune import run_distill_batches

    calls = {"n": 0}

    def _fake_distill(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"processed_events": 2, "atoms_created": 4}
        return {"processed_events": 0, "atoms_created": 0}

    monkeypatch.setattr(
        "agent_reach.daily_run.storage.distill.run_distill",
        _fake_distill,
    )
    result = run_distill_batches(batch_limit=100, max_rounds=0)
    assert result["processed_events"] == 4
    assert result["rounds"] == 3
    assert result["unlimited"] is True
