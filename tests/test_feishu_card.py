# -*- coding: utf-8
"""Tests for Feishu card element builder."""

from agent_reach.integrations.feishu_card import (
    build_card_elements,
    build_card_payloads,
    split_elements_by_table_limit,
)


class TestFeishuCard:
    def test_build_card_elements_plain(self):
        els = build_card_elements("Hello **world**")
        assert len(els) == 1
        assert els[0]["tag"] == "markdown"

    def test_build_card_elements_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        els = build_card_elements(md)
        assert any(e.get("tag") == "table" for e in els)

    def test_split_elements_by_table_limit(self):
        t1 = {"tag": "table", "columns": [], "rows": []}
        t2 = {"tag": "table", "columns": [], "rows": []}
        groups = split_elements_by_table_limit(
            [{"tag": "markdown", "content": "x"}, t1, t2],
            max_tables=1,
        )
        assert len(groups) == 2
        assert groups[0][-1]["tag"] == "table"
        assert groups[1][0]["tag"] == "table"

    def test_build_card_payloads_splits_tables(self):
        md = (
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "middle\n\n"
            "| C | D |\n|---|---|\n| 3 | 4 |"
        )
        payloads = build_card_payloads("T", md, split_tables=True)
        assert len(payloads) == 2
