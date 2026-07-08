# -*- coding: utf-8 -*-
"""Optional outbound integrations (Feishu, etc.)."""

from agent_reach.integrations.feishu import (
    FeishuError,
    build_card,
    check_feishu,
    feishu_mode,
    send_card,
)

__all__ = [
    "FeishuError",
    "build_card",
    "check_feishu",
    "feishu_mode",
    "send_card",
]
