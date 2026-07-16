# -*- coding: utf-8 -*-
"""Tests for Feishu notification integration."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_reach.config import Config
from agent_reach.integrations.feishu import (
    FeishuError,
    build_card,
    check_feishu,
    feishu_mode,
    send_card,
)


@pytest.fixture
def tmp_config(tmp_path):
    cfg = Config(config_path=tmp_path / "config.yaml")
    return cfg


class TestFeishuConfig:
    def test_mode_off_when_empty(self, tmp_config):
        assert feishu_mode(tmp_config) is None
        status, _, _ = check_feishu(tmp_config)
        assert status == "off"

    def test_mode_webhook(self, tmp_config):
        tmp_config.set("feishu_webhook_url", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
        assert feishu_mode(tmp_config) == "webhook"
        status, message, backend = check_feishu(tmp_config)
        assert status == "ok"
        assert "Webhook" in message
        assert backend == "Webhook Bot"

    def test_mode_app_requires_all_fields(self, tmp_config):
        tmp_config.set("feishu_app_id", "cli_test")
        tmp_config.set("feishu_app_secret", "secret")
        assert feishu_mode(tmp_config) is None
        status, message, _ = check_feishu(tmp_config)
        assert status == "warn"
        assert "FEISHU_CHAT_ID" in message

    def test_build_card(self):
        card = build_card("Title", "Hello **world**", template="orange")
        assert card["header"]["title"]["content"] == "Title"
        assert card["header"]["template"] == "orange"
        assert card["elements"][0]["tag"] == "markdown"
        assert card["elements"][0]["content"] == "Hello **world**"


class TestFeishuSend:
    @patch("agent_reach.integrations.feishu.requests.post")
    def test_send_app_card(self, mock_post, tmp_config):
        tmp_config.set("feishu_app_id", "cli_test")
        tmp_config.set("feishu_app_secret", "secret")
        tmp_config.set("feishu_chat_id", "oc_test")

        mock_post.side_effect = [
            MagicMock(json=lambda: {"code": 0, "tenant_access_token": "tok123"}),
            MagicMock(json=lambda: {"code": 0, "msg": "success", "data": {"message_id": "om_x"}}),
        ]

        result = send_card(tmp_config, "Test", "Body", template="blue")
        assert result["code"] == 0
        assert mock_post.call_count == 2
        send_payload = mock_post.call_args_list[1].kwargs["json"]
        content = json.loads(send_payload["content"])
        assert content["header"]["title"]["content"] == "Test"

    @patch("agent_reach.integrations.feishu.requests.post")
    def test_send_webhook_card(self, mock_post, tmp_config):
        tmp_config.set("feishu_webhook_url", "https://open.feishu.cn/open-apis/bot/v2/hook/key")
        mock_post.return_value = MagicMock(json=lambda: {"code": 0, "msg": "success"})

        result = send_card(tmp_config, "Webhook", "Ping")
        assert result["code"] == 0
        payload = mock_post.call_args.kwargs["json"]
        assert payload["msg_type"] == "interactive"
        assert payload["card"]["header"]["title"]["content"] == "Webhook"

    def test_send_without_config_raises(self, tmp_config):
        with pytest.raises(FeishuError):
            send_card(tmp_config, "X", "Y")
