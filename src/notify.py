#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отправка сообщений в Telegram. Только стандартная библиотека (urllib).

Токен и chat_id берутся из переменных окружения (НИКОГДА не из кода/репозитория):
  TG_BOT_TOKEN — токен бота от @BotFather
  TG_CHAT_ID   — id чата/пользователя (см. docs/telegram_setup.md)

Использование:
  from notify import send_telegram
  send_telegram("Привет!")            # вернёт True/False
  python3 src/notify.py "тестовое сообщение"   # быстрый тест из консоли
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(text: str,
                  token: str | None = None,
                  chat_id: str | None = None,
                  parse_mode: str = "Markdown",
                  disable_preview: bool = True) -> bool:
    token = token or os.environ.get("TG_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print("[notify] нет TG_BOT_TOKEN / TG_CHAT_ID — пропускаю отправку "
              "(см. docs/telegram_setup.md)", file=sys.stderr)
        return False

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if disable_preview else "false",
    }).encode()

    req = urllib.request.Request(API.format(token=token), data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
            if not payload.get("ok"):
                print(f"[notify] Telegram error: {payload}", file=sys.stderr)
                return False
            return True
    except Exception as e:  # noqa: BLE001 — нам важно не уронить пайплайн из-за сети
        print(f"[notify] не смог отправить: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "✅ findwork: тестовое сообщение"
    ok = send_telegram(msg)
    print("отправлено" if ok else "не отправлено (проверь токен/chat_id)")
    sys.exit(0 if ok else 1)
