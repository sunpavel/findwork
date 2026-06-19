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
import time
import urllib.error
import urllib.request

OPENAI_DEFAULT_MODEL = "gpt-5"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"


def _openai_url() -> str:
    # OPENAI_BASE_URL позволяет указать совместимый прокси-эндпоинт (нужно для РФ,
    # где api.openai.com отдаёт 403 unsupported_country). Пример: https://api.proxyapi.ru/openai/v1
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return base + "/chat/completions"


def _anthropic_url() -> str:
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    return base + "/v1/messages"


class LLMError(RuntimeError):
    pass


def _post(url: str, headers: dict, payload: dict, timeout: int = 240, retries: int = 3) -> dict:
    # LLM_PROXY (http/https-прокси в поддерживаемой стране) — обход гео-блокировок РФ.
    # Без него urllib и так уважает переменные окружения HTTPS_PROXY/HTTP_PROXY.
    proxy = os.environ.get("LLM_PROXY")
    opener = (urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else None)
    open_fn = opener.open if opener else urllib.request.urlopen
    data = json.dumps(payload).encode("utf-8")
    last = ""
    # Бесплатные OpenAI-совместимые шлюзы (OpenRouter) часто отдают 429 — как HTTP-статус
    # или как 200 с телом {"error": {... code: 429 ...}}. Ретраим с паузой (retry_after).
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with open_fn(req, timeout=timeout) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < retries:
                last = text[:120]; time.sleep(min(2 ** attempt, 20)); continue
            raise LLMError(f"HTTP {e.code}: {text[:400]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"сеть: {e.reason}") from e
        err = d.get("error")
        if err:
            code, msg = err.get("code"), (err.get("message") or "")
            if code == 429 and attempt < retries:
                wait = (err.get("metadata") or {}).get("retry_after_seconds") or 2 ** attempt
                last = msg; time.sleep(min(float(wait), 25)); continue
            raise LLMError(f"LLM error {code}: {msg[:400]}")
        return d
    raise LLMError(f"429 не отпустил за {retries} попыток: {last[:200]}")


def _openai(system: str, user: str, *, model: str, max_tokens: int, json_mode: bool) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise LLMError("нет OPENAI_API_KEY")
    # Модель вида "vendor/model" = бесплатный OpenAI-совместимый шлюз (OpenRouter и т.п.):
    # такие шлют max_tokens, а не max_completion_tokens (его понимает только api.openai.com).
    compat = "/" in model
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        ("max_tokens" if compat else "max_completion_tokens"): max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "minimal")
    if compat:
        # OpenRouter: ограничиваем глубину раздумий reasoning-моделей (gpt-oss и пр.) —
        # иначе они думают десятки секунд и нередко оставляют пустой content. Модели без
        # reasoning этот параметр игнорируют.
        payload["reasoning"] = {"effort": {"minimal": "low"}.get(effort, effort) or "low"}
    elif effort and model.startswith(("gpt-5", "o1", "o3", "o4")):
        payload["reasoning_effort"] = effort
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if compat:
        headers["HTTP-Referer"] = "https://github.com/sunpavel/findwork"
        headers["X-Title"] = "findwork"
    d = _post(_openai_url(), headers, payload)
    return d["choices"][0]["message"]["content"] or ""


def _anthropic(system: str, user: str, *, model: str, max_tokens: int, json_mode: bool) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("нет ANTHROPIC_API_KEY")
    messages = [{"role": "user", "content": user}]
    if json_mode:
        # префилл "{" заставляет Claude отвечать чистым JSON без преамбулы.
        messages.append({"role": "assistant", "content": "{"})
    d = _post(_anthropic_url(), {"x-api-key": key, "anthropic-version": "2023-06-01",
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
    """Достаёт JSON-объект из ответа (на случай обёрток ```json / преамбул).

    Пустой ответ (бесплатные reasoning-модели иногда отдают content="") и
    неразбираемый текст превращаем в LLMError — чтобы пайплайн мог деградировать,
    а не падать сырым JSONDecodeError.
    """
    text = (text or "").strip()
    if not text:
        raise LLMError("пустой ответ модели (нет JSON)")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # берём от первой { до последней }
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                pass
        raise LLMError(f"ответ не похож на JSON: {text[:200]!r}")


def complete_json(system: str, user: str, *, provider: str, model: str | None = None,
                  max_tokens: int = 8000) -> dict:
    """Как complete(), но возвращает разобранный JSON-объект."""
    return _extract_json(complete(system, user, provider=provider, model=model,
                                  max_tokens=max_tokens, json_mode=True))


def has_provider(provider: str) -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") if provider == "openai"
                else os.environ.get("ANTHROPIC_API_KEY"))
