# -*- coding: utf-8
"""Minimal OpenAI-compatible chat completion for daily-run LLM refine."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

_DEFAULT_DEEPSEEK_BASE = "https://api.deepseek.com"


def chat_completions_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to a chat/completions endpoint."""
    base = str(base_url or _DEFAULT_DEEPSEEK_BASE).strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _resolve_api_key(provider: str) -> tuple[str, str]:
    from agent_reach.config import Config

    cfg = Config()
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY") or cfg.get("groq_api_key") or ""
        return str(key).strip(), "https://api.groq.com/openai/v1/chat/completions"
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY") or cfg.get("openai_api_key") or ""
        return str(key).strip(), "https://api.openai.com/v1/chat/completions"
    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY") or cfg.get("deepseek_api_key") or ""
        base = (
            os.environ.get("DEEPSEEK_BASE_URL")
            or cfg.get("deepseek_base_url")
            or _DEFAULT_DEEPSEEK_BASE
        )
        return str(key).strip(), chat_completions_url(str(base))
    raise ValueError(f"unknown provider: {provider}")


def resolve_chat_provider(preferred: str = "auto") -> Optional[str]:
    """Return configured provider name, or None when no key is available."""
    if preferred != "auto":
        key, _ = _resolve_api_key(preferred)
        return preferred if key else None
    for provider in ("deepseek", "groq", "openai"):
        key, _ = _resolve_api_key(provider)
        if key:
            return provider
    return None


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _default_models() -> dict[str, str]:
    return {
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o-mini",
        "deepseek": "deepseek-chat",
    }


def _provider_chain(preferred: str = "auto") -> list[str]:
    if preferred != "auto":
        primary = preferred if resolve_chat_provider(preferred) else None
        chain = [primary] if primary else []
    else:
        chain = [p for p in ("deepseek", "groq", "openai") if resolve_chat_provider(p)]
    seen: set[str] = set()
    out: list[str] = []
    for name in chain:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    for fallback in ("deepseek", "groq", "openai"):
        if fallback not in seen and resolve_chat_provider(fallback):
            out.append(fallback)
            seen.add(fallback)
    return out


def _chat_completion_text(
    *,
    system: str,
    user: str,
    provider: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 45,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    max_retries: Optional[int] = None,
) -> Optional[str]:
    api_key, endpoint = _resolve_api_key(provider)
    if not api_key:
        return None
    use_model = model or _default_models().get(provider, _default_models()["deepseek"])
    payload: dict[str, Any] = {
        "model": use_model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens is not None and int(max_tokens) > 0:
        payload["max_tokens"] = int(max_tokens)

    retries = 0 if max_retries is None else max(0, int(max_retries))
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            if attempt >= retries:
                return None
            continue
        choices = body.get("choices") or []
        if not choices:
            if attempt >= retries:
                return None
            continue
        content = ((choices[0] or {}).get("message") or {}).get("content") or ""
        if content:
            return str(content)
        if attempt >= retries:
            return None
    return None


def chat_text_with_fallback(
    *,
    system: str,
    user: str,
    provider: str = "auto",
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 45,
    max_tokens: Optional[int] = None,
    max_retries: Optional[int] = None,
    fallback_text: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Try providers in chain; return (text, provider_used)."""
    for name in _provider_chain(provider):
        text = _chat_completion_text(
            system=system,
            user=user,
            provider=name,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
            max_retries=max_retries,
            json_mode=False,
        )
        if text:
            return text, name
    if fallback_text:
        return fallback_text, None
    return None, None


def chat_json(
    *,
    system: str,
    user: str,
    provider: str = "auto",
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 45,
    max_tokens: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Call chat completions and parse a JSON object from the assistant reply."""
    for name in _provider_chain(provider):
        content = _chat_completion_text(
            system=system,
            user=user,
            provider=name,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
            max_retries=max_retries,
            json_mode=True,
        )
        if not content:
            continue
        parsed = _extract_json(content)
        if parsed is not None:
            parsed.setdefault("_llm_provider", name)
            return parsed
    return None
