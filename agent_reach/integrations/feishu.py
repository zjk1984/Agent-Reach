# -*- coding: utf-8 -*-
"""Feishu (Lark) notification integration for Agent Reach."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional, Tuple

import requests

from agent_reach.config import Config
from agent_reach.integrations.feishu_card import build_card_payloads

DEFAULT_DOMAIN = "feishu"
API_HOSTS = {
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
}


class FeishuError(RuntimeError):
    """Raised when Feishu API calls fail."""


def _api_base(config: Config) -> str:
    domain = (config.get("feishu_domain") or DEFAULT_DOMAIN).strip().lower()
    return API_HOSTS.get(domain, API_HOSTS[DEFAULT_DOMAIN])


def feishu_mode(config: Config) -> Optional[str]:
    """Return active push mode: app, webhook, or None if not configured."""
    webhook = (config.get("feishu_webhook_url") or "").strip()
    if webhook:
        return "webhook"
    app_id = (config.get("feishu_app_id") or "").strip()
    app_secret = (config.get("feishu_app_secret") or "").strip()
    chat_id = (config.get("feishu_chat_id") or "").strip()
    if app_id and app_secret and chat_id:
        return "app"
    return None


def check_feishu(config: Config) -> Tuple[str, str, Optional[str]]:
    """Check Feishu notification readiness."""
    mode = feishu_mode(config)
    if mode == "webhook":
        return "ok", "Webhook 已配置（群机器人推送）", "Webhook Bot"
    if mode == "app":
        try:
            get_tenant_access_token(config)
        except FeishuError as exc:
            return "warn", f"App 凭证已配置但鉴权失败：{exc}", "App Bot API"
        chat_id = (config.get("feishu_chat_id") or "").strip()
        short_id = f"{chat_id[:8]}..." if len(chat_id) > 8 else chat_id
        return "ok", f"App Bot 已就绪（chat_id={short_id}）", "App Bot API"

    app_id = (config.get("feishu_app_id") or "").strip()
    app_secret = (config.get("feishu_app_secret") or "").strip()
    if app_id or app_secret:
        return (
            "warn",
            "已配置 FEISHU_APP_ID/SECRET，但缺少 FEISHU_CHAT_ID 或 FEISHU_WEBHOOK_URL",
            None,
        )
    return (
        "off",
        "未配置。运行：agent-reach configure feishu-app-id / feishu-app-secret / feishu-chat-id",
        None,
    )


def get_tenant_access_token(config: Config, timeout: float = 15.0) -> str:
    app_id = (config.get("feishu_app_id") or "").strip()
    app_secret = (config.get("feishu_app_secret") or "").strip()
    if not app_id or not app_secret:
        raise FeishuError("缺少 feishu_app_id 或 feishu_app_secret")

    url = f"{_api_base(config)}/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(
        url,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise FeishuError(data.get("msg") or resp.text)
    token = data.get("tenant_access_token")
    if not token:
        raise FeishuError("tenant_access_token 为空")
    return token


def build_card(
    title: str,
    markdown: str,
    *,
    template: str = "blue",
    split_tables: bool = True,
) -> dict[str, Any]:
    """Build a single Feishu card (first chunk when markdown has multiple tables)."""
    return build_card_payloads(title, markdown, template=template, split_tables=split_tables)[0]


def _title_with_part(title: str, index: int, total: int) -> str:
    if total <= 1:
        return title
    return f"{title} ({index}/{total})"


def send_card(
    config: Config,
    title: str,
    markdown: str,
    *,
    template: str = "blue",
    timeout: float = 15.0,
    split_tables: bool = True,
    interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """Send one or more interactive cards to Feishu using the configured mode."""
    mode = feishu_mode(config)
    if mode not in ("webhook", "app"):
        raise FeishuError(
            "飞书未配置。请设置 FEISHU_WEBHOOK_URL，或 FEISHU_APP_ID + FEISHU_APP_SECRET + FEISHU_CHAT_ID"
        )

    payloads = build_card_payloads(title, markdown, template=template, split_tables=split_tables)
    results: list[dict[str, Any]] = []
    total = len(payloads)
    for i, card in enumerate(payloads, start=1):
        card_title = _title_with_part(title, i, total)
        card = dict(card)
        card["header"] = dict(card["header"])
        card["header"]["title"] = dict(card["header"]["title"])
        card["header"]["title"]["content"] = card_title
        if mode == "webhook":
            results.append(_send_webhook_card_payload(config, card, timeout=timeout))
        else:
            results.append(_send_app_card_payload(config, card, timeout=timeout))
        if interval_seconds > 0 and i < total:
            time.sleep(interval_seconds)

    if total == 1:
        return results[0]
    return {
        "code": 0,
        "cards": total,
        "results": results,
        "feishu": results[-1],
    }


def _send_app_card_payload(
    config: Config,
    card: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    token = get_tenant_access_token(config, timeout=timeout)
    chat_id = (config.get("feishu_chat_id") or "").strip()
    receive_id_type = (config.get("feishu_receive_id_type") or "chat_id").strip()
    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    url = f"{_api_base(config)}/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload,
        timeout=timeout,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise FeishuError(data.get("msg") or resp.text)
    return data


def _webhook_sign(secret: str) -> Tuple[str, str]:
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return timestamp, sign


def _send_webhook_card_payload(
    config: Config,
    card: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    webhook_url = (config.get("feishu_webhook_url") or "").strip()
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": card,
    }
    secret = (config.get("feishu_webhook_secret") or "").strip()
    if secret:
        timestamp, sign = _webhook_sign(secret)
        payload["timestamp"] = timestamp
        payload["sign"] = sign

    resp = requests.post(webhook_url, json=payload, timeout=timeout)
    data = resp.json()
    if data.get("code") not in (0, None) and data.get("StatusCode") not in (0, None):
        if data.get("code") != 0:
            raise FeishuError(data.get("msg") or resp.text)
    if data.get("StatusCode") not in (None, 0):
        raise FeishuError(data.get("StatusMessage") or resp.text)
    return data
