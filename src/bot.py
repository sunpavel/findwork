#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот findwork (long polling, только stdlib).

Логика (по решению кандидата):
  • HH.ru — присылаешь ссылку на вакансию → бот готовит резюме под вакансию и
    сопроводительное, показывает их и спрашивает кнопкой «✅ Откликнуться».
    Отклик уходит ТОЛЬКО после твоего подтверждения (полу-авто).
  • facancy.ru и другие сайты — бот достаёт текст вакансии, генерит резюме и
    сопроводительное и ПРИСЫЛАЕТ их тебе (режим «ассистент»); отклик ты делаешь
    сам на сайте — авто-отправки там нет.

Команды: /pause /resume /status /dry <url> /help.
Безопасность: реагирует только на сообщения из чата TG_CHAT_ID.

Запуск:  TG_BOT_TOKEN=... TG_CHAT_ID=... python3 src/bot.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply as apply_mod
import hh_app
import tailor as tailor_mod
import webvac

API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "🤖 *findwork*\n\n"
    "• Пришли *ссылку на вакансию HH* → подготовлю резюме и письмо и спрошу подтверждение "
    "перед откликом.\n"
    "• Пришли *ссылку facancy.ru* (или другого сайта) → пришлю тебе резюме и письмо, "
    "отклик сделаешь сам на сайте.\n\n"
    "Команды: /health · /status · /pause · /resume · /dry <ссылка> · /help"
)

# token -> apply_mod.Prepared (ожидают подтверждения кнопкой)
_PENDING: dict[str, object] = {}
_PENDING_MAX = 50


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


def send(chat_id, text: str, buttons: list | None = None) -> None:
    params = {
        "chat_id": chat_id, "text": text,
        "parse_mode": "Markdown", "disable_web_page_preview": "true",
    }
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        _api("sendMessage", params, timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"[bot] send error: {e}", file=sys.stderr)


def _answer_callback(cb_id: str, text: str = "") -> None:
    try:
        _api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text}, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"[bot] answerCallback error: {e}", file=sys.stderr)


# --- классификация входящего --------------------------------------------------

_URL_RE = re.compile(r"https?://\S+", re.I)


def _is_hh(text: str) -> bool:
    t = text.strip()
    return ("hh.ru/vacancy/" in t) or ("vacancyId=" in t) or t.isdigit()


def _find_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    return m.group(0) if m else None


# --- HH: подготовка + подтверждение ------------------------------------------

def _store_pending(p) -> str:
    if len(_PENDING) >= _PENDING_MAX:
        _PENDING.pop(next(iter(_PENDING)))  # выкидываем самый старый
    token = uuid.uuid4().hex[:10]
    _PENDING[token] = p
    return token


def _handle_hh(chat_id, target: str) -> None:
    send(chat_id, "⏳ Готовлю резюме и сопроводительное под вакансию HH…")
    try:
        p = apply_mod.prepare(target)
    except hh_app.HHAppError as e:
        msg = f"❌ Ошибка HH: {e}"
        if e.body:
            msg += f"\n```\n{e.body[:300]}\n```"
        send(chat_id, msg)
        return
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"❌ Ошибка: {e}")
        return

    if p.blocked:
        send(chat_id, p.block_reason)
        return

    token = _store_pending(p)
    overrides = p.resume_overrides
    skills = ", ".join(overrides.get("skill_set", [])[:12])
    text = (
        f"🎯 *{p.title}* — {p.company}\n"
        f"Скор: *{p.score}/100*\n\n"
        f"📄 *Резюме под вакансию:* «{overrides.get('title', '')}»\n"
        f"_Навыки:_ {skills}\n\n"
        f"✉️ *Сопроводительное:*\n{p.cover_letter}\n\n"
        f"_Текст: {p.tailor_source}._ Отправить отклик этим резюме и письмом?"
    )
    buttons = [[
        {"text": "✅ Откликнуться", "callback_data": f"a:{token}"},
        {"text": "✖️ Отмена", "callback_data": f"c:{token}"},
    ]]
    send(chat_id, text, buttons=buttons)


def _handle_confirm(chat_id, token: str) -> None:
    p = _PENDING.pop(token, None)
    if p is None:
        send(chat_id, "⌛️ Эта заявка уже неактуальна — пришли ссылку заново.")
        return
    send(chat_id, "⏳ Создаю резюме под вакансию и отправляю отклик…")
    try:
        res = apply_mod.commit(p)
    except hh_app.HHAppError as e:
        msg = f"❌ Ошибка HH при отправке: {e}"
        if e.body:
            msg += f"\n```\n{e.body[:300]}\n```"
        send(chat_id, msg)
        return
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"❌ Ошибка при отправке: {e}")
        return
    notes = ("\n\n_" + "; ".join(res.notes) + "_") if res.notes else ""
    send(chat_id, res.message + notes)


# --- Ассистент (facancy.ru и пр.): материалы без отправки ---------------------

def _handle_assist(chat_id, url: str) -> None:
    site = urllib.parse.urlparse(url).netloc or "сайт"
    send(chat_id, f"⏳ Беру вакансию с {site}, готовлю резюме и письмо…")
    try:
        vacancy = webvac.fetch_vacancy(url)
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"⚠️ Не смог открыть страницу ({e}). "
                      f"Пришли текст вакансии сообщением — соберу по нему.")
        return
    tr = tailor_mod.tailor(vacancy)
    ov = tr.resume_overrides
    skills = ", ".join(ov.get("skill_set", [])[:12])
    text = (
        f"🧩 *Ассистент ({site})* — отклик делаешь сам на сайте.\n\n"
        f"🎯 *{vacancy.get('name', 'Вакансия')}*\n\n"
        f"📄 *Резюме (черновик под вакансию):* «{ov.get('title', '')}»\n"
        f"_Навыки:_ {skills}\n"
        f"_О себе:_ {ov.get('skills', '')}\n\n"
        f"✉️ *Сопроводительное:*\n{tr.cover_letter}\n\n"
        f"🔗 {url}\n_Текст: {tr.source}._"
    )
    send(chat_id, text)


# --- здоровье/диагностика -----------------------------------------------------

def _health_text() -> str:
    """Что подключено: Telegram / Anthropic / HH — видно прямо в чате."""
    lines = ["🩺 *Проверка подключений*", ""]

    # Telegram — если это сообщение дошло, значит работает.
    lines.append("• Telegram: ✅ бот отвечает")

    # LLM для писем — активный провайдер.
    prov = tailor_mod._provider()
    if prov == "openai":
        model = os.environ.get("OPENAI_MODEL", tailor_mod.OPENAI_DEFAULT_MODEL)
        lines.append(f"• Письма (LLM): ✅ OpenAI {model}")
    elif prov == "anthropic":
        try:
            import anthropic  # noqa: F401, PLC0415
            sdk = True
        except Exception:  # noqa: BLE001
            sdk = False
        model = os.environ.get("ANTHROPIC_MODEL", tailor_mod.DEFAULT_MODEL)
        if sdk:
            lines.append(f"• Письма (LLM): ✅ Claude {model}")
        else:
            lines.append("• Письма (LLM): ⚠️ ключ Claude есть, нет пакета `anthropic` → "
                         "шаблон (`pip install -r requirements.txt`)")
    else:
        lines.append("• Письма (LLM): ⚠️ нет ключа OPENAI/ANTHROPIC → письма по шаблону")

    # HH — токен приложения (серый путь, нужен для откликов).
    try:
        me = hh_app.whoami()
        name = f"{me.get('first_name', '')} {me.get('last_name', '')}".strip() or me.get("id", "?")
        n_res = len(hh_app.list_resumes())
        lines.append(f"• HH (отклики): ✅ авторизован как {name}, резюме: {n_res}")
    except hh_app.HHAppError as e:
        if e.status:
            lines.append(f"• HH (отклики): ❌ HTTP {e.status} — токен есть, но запрос отклонён")
        else:
            lines.append("• HH (отклики): ❌ не авторизовано — выполни "
                         "`hh-applicant-tool authorize` (см. docs/QUICKSTART.md)")
    except Exception as e:  # noqa: BLE001
        lines.append(f"• HH (отклики): ❌ {e}")

    paused = "⏸ да" if apply_mod.is_paused() else "▶️ нет"
    lines.append("")
    lines.append(f"Пауза: {paused} · лимит/день: {apply_mod.daily_limit()} · "
                 f"ждут подтверждения: {len(_PENDING)}")
    return "\n".join(lines)


# --- роутинг ------------------------------------------------------------------

def _handle_message(msg: dict) -> None:
    chat_id = (msg.get("chat") or {}).get("id")
    allowed = _chat_id()
    if allowed and str(chat_id) != str(allowed):
        print(f"[bot] игнор сообщения из чата {chat_id} (разрешён {allowed})", file=sys.stderr)
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text in ("/start", "/help"):
        send(chat_id, HELP)
    elif text == "/health":
        try:
            send(chat_id, _health_text())
        except Exception as e:  # noqa: BLE001
            send(chat_id, f"❌ /health: {e}")
    elif text == "/status":
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            apply_mod._print_status()
        extra = f"\nЖдут подтверждения: {len(_PENDING)}"
        send(chat_id, "📊 *Статус*\n```\n" + buf.getvalue().strip() + extra + "\n```")
    elif text == "/pause":
        apply_mod.set_paused(True)
        send(chat_id, "⏸ Авто-отклик на паузе. Сниму по /resume.")
    elif text == "/resume":
        apply_mod.set_paused(False)
        send(chat_id, "▶️ Пауза снята.")
    elif text.startswith("/dry"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "Использование: /dry <ссылка на вакансию>")
        elif _is_hh(parts[1]):
            try:
                res = apply_mod.apply_to(parts[1].strip(), dry_run=True)
                send(chat_id, f"{res.message}\n\n✉️ {res.cover_letter}")
            except Exception as e:  # noqa: BLE001
                send(chat_id, f"❌ {e}")
        else:
            _handle_assist(chat_id, parts[1].strip())
    elif _is_hh(text):
        _handle_hh(chat_id, text)
    elif _find_url(text):
        _handle_assist(chat_id, _find_url(text))
    else:
        send(chat_id, "Не похоже на вакансию. Пришли ссылку (HH или facancy.ru) или /help.")


def _handle_callback(cb: dict) -> None:
    chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
    allowed = _chat_id()
    if allowed and str(chat_id) != str(allowed):
        _answer_callback(cb.get("id", ""), "Нет доступа")
        return
    data = cb.get("data", "")
    _answer_callback(cb.get("id", ""))
    if data.startswith("a:"):
        _handle_confirm(chat_id, data[2:])
    elif data.startswith("c:"):
        _PENDING.pop(data[2:], None)
        send(chat_id, "✖️ Отменено — отклик не отправлен.")


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
            params = {"timeout": 50, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None:
                params["offset"] = offset
            resp = _api("getUpdates", params, timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"[bot] getUpdates error: {e}", file=sys.stderr)
            time.sleep(3)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if upd.get("callback_query"):
                    _handle_callback(upd["callback_query"])
                else:
                    msg = upd.get("message") or upd.get("edited_message")
                    if msg:
                        _handle_message(msg)
            except Exception as e:  # noqa: BLE001 — одно сообщение не должно валить бота
                print(f"[bot] handler error: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        print("\n[bot] остановлен.")
