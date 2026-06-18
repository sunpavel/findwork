#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Провайдер-агностичный вызов LLM (OpenAI / Anthropic) на чистом urllib.

Зачем отдельный модуль: двухагентный пайплайн (career_agent.py) гоняет несколько
вызовов к РАЗНЫМ моделям (gpt-5 пишет, Claude проверяет). Чтобы не плодить SDK-
зависимости, обе модели дёргаем по HTTP. JSON-ответ парсим устойчиво.

Ключи и модели — из окружения:
  OPENAI_API_KEY,    OPENAI_MODEL (по умолчанию gpt-5),      OPENAI_REASONING_EFFORT (minimal)
  ANTHROPIC_API_KEY, ANTHROPIC_MODEL (по умолчанию claude-opus-4-8)
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_DEFAULT_MODEL = "gpt-5"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"


class LLMError(RuntimeError):
    pass


def _post(url: str, headers: dict, payload: dict, timeout: int = 240) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"сеть: {e.reason}") from e


def _openai(system: str, user: str, *, model: str, max_tokens: int, json_mode: bool) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise LLMError("нет OPENAI_API_KEY")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "minimal")
    if effort and model.startswith(("gpt-5", "o1", "o3", "o4")):
        payload["reasoning_effort"] = effort
    d = _post(OPENAI_URL, {"Authorization": f"Bearer {key}",
                           "Content-Type": "application/json"}, payload)
    return d["choices"][0]["message"]["content"] or ""


def _anthropic(system: str, user: str, *, model: str, max_tokens: int, json_mode: bool) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("нет ANTHROPIC_API_KEY")
    messages = [{"role": "user", "content": user}]
    if json_mode:
        # префилл "{" заставляет Claude отвечать чистым JSON без преамбулы.
        messages.append({"role": "assistant", "content": "{"})
    d = _post(ANTHROPIC_URL, {"x-api-key": key, "anthropic-version": "2023-06-01",
                              "Content-Type": "application/json"},
              {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages})
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    return ("{" + text) if json_mode else text


def complete(system: str, user: str, *, provider: str, model: str | None = None,
             max_tokens: int = 8000, json_mode: bool = False) -> str:
    """Единый вызов модели. provider: openai | anthropic."""
    if provider == "openai":
        return _openai(system, user, model=model or os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL),
                       max_tokens=max_tokens, json_mode=json_mode)
    if provider == "anthropic":
        return _anthropic(system, user, model=model or os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL),
                          max_tokens=max_tokens, json_mode=json_mode)
    raise LLMError(f"неизвестный провайдер: {provider}")


def _extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа (на случай обёрток ```json / преамбул)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # берём от первой { до последней }
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(text[i:j + 1])
        raise


def complete_json(system: str, user: str, *, provider: str, model: str | None = None,
                  max_tokens: int = 8000) -> dict:
    """Как complete(), но возвращает разобранный JSON-объект."""
    return _extract_json(complete(system, user, provider=provider, model=model,
                                  max_tokens=max_tokens, json_mode=True))


def has_provider(provider: str) -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") if provider == "openai"
                else os.environ.get("ANTHROPIC_API_KEY"))
