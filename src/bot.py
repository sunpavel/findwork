#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот управления авто-откликом (long polling, только stdlib).

Что умеет:
  • присылаешь ССЫЛКУ на вакансию hh.ru (или её id) → бот под неё создаёт резюме,
    пишет сопроводительное и сам откликается (полный авто-режим);
  • /pause  — поставить авто-отклик на паузу (ты просил «команду паузы»);
  • /resume — снять паузу;
  • /status — статус, дневной лимит, режим резюме;
  • /dry <ссылка> — «сухой» прогон: показать письмо и скор, НЕ отправляя отклик;
  • /help — помощь.

Безопасность: бот реагирует только на сообщения из чата TG_CHAT_ID (твой chat_id).

Запуск:
  TG_BOT_TOKEN=... TG_CHAT_ID=... python3 src/bot.py
На сервере — под systemd (см. docs/auto_apply.md).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply as apply_mod
import hh_app

API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "🤖 *findwork — авто-отклик*\n\n"
    "Пришли *ссылку на вакансию* hh.ru (или её id) — я под неё подготовлю резюме и "
    "сопроводительное и откликнусь.\n\n"
    "Команды:\n"
    "• /status — статус и лимиты\n"
    "• /pause — пауза авто-отклика\n"
    "• /resume — снять паузу\n"
    "• /dry <ссылка> — показать письмо и скор без отправки\n"
    "• /help — это сообщение"
)


def _token() -> str:
    tok = os.environ.get("TG_BOT_TOKEN")
    if not tok:
        sys.exit("Не задан TG_BOT_TOKEN (см. docs/telegram_setup.md)")
    return tok


def _chat_id() -> str | None:
    return os.environ.get("TG_CHAT_ID")


def _api(method: str, params: dict, timeout: int = 60) -> dict:
    url = API.format(token=_token(), method=method)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(chat_id: str | int, text: str) -> None:
    try:
        _api("sendMessage", {
            "chat_id": chat_id, "text": text,
            "parse_mode": "Markdown", "disable_web_page_preview": "true",
        }, timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"[bot] send error: {e}", file=sys.stderr)


def _looks_like_vacancy(text: str) -> bool:
    t = text.strip()
    return ("hh.ru/vacancy/" in t) or ("vacancyId=" in t) or t.isdigit()


def _handle_apply(chat_id, target: str, dry_run: bool) -> None:
    try:
        vid = hh_app.parse_vacancy_id(target)
    except hh_app.HHAppError as e:
        send(chat_id, f"⚠️ {e}")
        return
    send(chat_id, f"⏳ Беру вакансию {vid}, готовлю резюме и сопроводительное…")
    try:
        res = apply_mod.apply_to(target, dry_run=dry_run)
    except hh_app.HHAppError as e:
        msg = f"❌ Ошибка HH: {e}"
        if e.body:
            msg += f"\n```\n{e.body[:300]}\n```"
        send(chat_id, msg)
        return
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"❌ Непредвиденная ошибка: {e}")
        return

    head = res.message
    body = ""
    if res.cover_letter:
        body = f"\n\n✉️ *Сопроводительное:*\n{res.cover_letter}"
    notes = ("\n\n_" + "; ".join(res.notes) + "_") if res.notes else ""
    send(chat_id, f"{head}{body}{notes}")


def _handle_message(msg: dict) -> None:
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    allowed = _chat_id()
    if allowed and str(chat_id) != str(allowed):
        # чужой чат — игнорируем (но отметим в логе)
        print(f"[bot] игнор сообщения из чата {chat_id} (разрешён {allowed})", file=sys.stderr)
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text in ("/start", "/help"):
        send(chat_id, HELP)
    elif text == "/status":
        # соберём статус из apply_mod
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            apply_mod._print_status()
        send(chat_id, "📊 *Статус*\n```\n" + buf.getvalue().strip() + "\n```")
    elif text == "/pause":
        apply_mod.set_paused(True)
        send(chat_id, "⏸ Авто-отклик на паузе. Сниму по /resume.")
    elif text == "/resume":
        apply_mod.set_paused(False)
        send(chat_id, "▶️ Пауза снята — снова откликаюсь на присланные вакансии.")
    elif text.startswith("/dry"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "Использование: /dry <ссылка на вакансию>")
        else:
            _handle_apply(chat_id, parts[1].strip(), dry_run=True)
    elif text.startswith("/apply"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "Использование: /apply <ссылка на вакансию>")
        else:
            _handle_apply(chat_id, parts[1].strip(), dry_run=False)
    elif _looks_like_vacancy(text):
        _handle_apply(chat_id, text, dry_run=False)
    else:
        send(chat_id, "Не похоже на вакансию. Пришли ссылку hh.ru/vacancy/… или /help.")


def run() -> int:
    print("[bot] запуск long-polling… (Ctrl+C для выхода)")
    if _chat_id():
        try:
            send(_chat_id(), "🤖 findwork-бот на связи. Пришли ссылку на вакансию или /help.")
        except Exception:  # noqa: BLE001
            pass
    offset = None
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            resp = _api("getUpdates", params, timeout=60)
        except Exception as e:  # noqa: BLE001 — сеть может моргать, не падаем
            print(f"[bot] getUpdates error: {e}", file=sys.stderr)
            time.sleep(3)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if msg:
                try:
                    _handle_message(msg)
                except Exception as e:  # noqa: BLE001 — одно сообщение не должно валить бота
                    print(f"[bot] handler error: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        print("\n[bot] остановлен.")
