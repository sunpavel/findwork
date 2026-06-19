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
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply as apply_mod
import career_agent
import hh_app
import tailor as tailor_mod
import verify
import webvac

API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "🤖 *findwork*\n\n"
    "• Пришли *ссылку на вакансию HH* → подготовлю резюме и письмо и спрошу подтверждение "
    "перед откликом.\n"
    "• Пришли *ссылку facancy.ru* (или другого сайта) → пришлю тебе резюме и письмо, "
    "отклик сделаешь сам на сайте.\n"
    "• Пришли *фото* → добавлю его в резюме (PDF и DOCX).\n\n"
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


def send_document(chat_id, path: str, caption: str = "") -> None:
    """Отправляет файл (PDF/DOCX) в чат через multipart/form-data."""
    boundary = "----findwork" + uuid.uuid4().hex
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1000]
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
             for k, v in fields.items()]
    with open(path, "rb") as f:
        data = f.read()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                  f'filename="{os.path.basename(path)}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n').encode())
    body = b"".join(parts) + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        API.format(token=_token(), method="sendDocument"), data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            r.read()
    except Exception as e:  # noqa: BLE001
        print(f"[bot] sendDocument error: {e}", file=sys.stderr)


RESUME_PHOTO = Path(__file__).resolve().parent.parent / "resume" / "photo.jpg"


def _download_telegram_file(file_id: str, dest: Path) -> None:
    """Скачивает файл из Telegram (getFile → download) в dest."""
    info = _api("getFile", {"file_id": file_id}, timeout=20)
    file_path = (info.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram не вернул file_path")
    url = f"https://api.telegram.org/file/bot{_token()}/{file_path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _handle_photo(chat_id, msg: dict) -> bool:
    """Сохраняет присланное фото как фото для резюме. Возвращает True, если фото было."""
    file_id = ""
    if msg.get("photo"):
        file_id = msg["photo"][-1]["file_id"]  # последний размер — самый крупный
    else:
        doc = msg.get("document") or {}
        if str(doc.get("mime_type", "")).startswith("image/"):
            file_id = doc.get("file_id", "")
    if not file_id:
        return False
    try:
        _download_telegram_file(file_id, RESUME_PHOTO)
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"⚠️ Не смог сохранить фото: {e}")
        return True
    send(chat_id, "📸 Фото сохранил навсегда — теперь оно ставится во *все* резюме "
                  "автоматически (PDF и DOCX). Повторно присылать не нужно.\n"
                  "Чтобы заменить — пришли новое фото; статус виден в /health.")
    return True


def _answer_callback(cb_id: str, text: str = "") -> None:
    try:
        _api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text}, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"[bot] answerCallback error: {e}", file=sys.stderr)


STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def _record_feedback(vac_id: str, sentiment: str) -> None:
    """Логируем 👍/👎 по вакансии (state/feedback.jsonl) — топливо для будущей
    подстройки подбора (поднимать похожее на 👍, занижать похожее на 👎)."""
    try:
        STATE_DIR.mkdir(exist_ok=True)
        rec = {"ts": int(time.time()), "id": vac_id, "sentiment": sentiment}
        with open(STATE_DIR / "feedback.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[bot] feedback write error: {e}", file=sys.stderr)


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
    text = (
        f"🎯 *{p.title}* — {p.company}\n"
        f"Скор: *{p.score}/100*\n\n"
        f"📄 Откликнусь резюме: «{p.resume_title or '—'}»\n"
        f"✉️ *Сопроводительное (под вакансию):*\n{p.cover_letter}\n"
    )
    if p.warnings:
        text += "\n⚠️ *Проверь перед отправкой* (мог не сверить с мастер-резюме):\n- " \
                + "\n- ".join(p.warnings) + "\n"
    text += f"\n_Текст: {p.tailor_source}._ Отправить отклик?"
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

    # HH откликается существующим резюме, но адаптированное (с фото) под вакансию
    # отдаём файлом — можно при желании обновить им резюме на HH вручную.
    if res.ok and getattr(p, "resume", None):
        try:
            import resume_doc  # noqa: PLC0415 — нужен fpdf2/python-docx
            with tempfile.TemporaryDirectory() as d:
                pdf, docx = resume_doc.render_both(p.resume, d)
                send_document(chat_id, pdf, "📄 Адаптированное резюме под вакансию (с фото)")
                send_document(chat_id, docx, "✏️ DOCX — можешь обновить им своё резюме на HH вручную")
        except Exception as e:  # noqa: BLE001 — файл не критичен для самого отклика
            print(f"[bot] resume file render failed: {e}", file=sys.stderr)


# --- Ассистент (facancy.ru и пр.): материалы без отправки ---------------------

def _keyword_match(vacancy: dict, resume: dict) -> str:
    """ATS-сигнал (механика Jobscan): покрывает ли резюме ключевые навыки вакансии.

    Логика матчинга — общая с QA-проходом (src/verify.py), чтобы цифра в боте и
    дотяжка в пайплайне не расходились."""
    cov, total, miss = verify.keyword_match(vacancy, resume)
    if not total:
        return ""
    line = f"🎯 Соответствие навыкам вакансии: {cov}/{total} ({round(100 * cov / total)}%)"
    if miss:
        line += "\n_Не отражены:_ " + ", ".join(miss[:8])
    return line


def _handle_assist(chat_id, url: str) -> None:
    site = urllib.parse.urlparse(url).netloc or "сайт"
    send(chat_id, f"⏳ Беру вакансию с {site}…")
    try:
        vacancy = webvac.fetch_vacancy(url)
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"⚠️ Не смог открыть страницу ({e}). "
                      f"Пришли текст вакансии сообщением — соберу по нему.")
        return

    send(chat_id, "🧠 Анализирую вакансию, пишу резюме и письмо, проверяю второй моделью… (~минуту)")
    try:
        app = career_agent.prepare_application(vacancy)
    except Exception as e:  # noqa: BLE001 — деградация на простой шаблон
        print(f"[bot] assist pipeline error: {e}", file=sys.stderr)  # детали в логи, не юзеру
        tr = tailor_mod.tailor(vacancy)
        send(chat_id, "⚠️ Не собрал полный комплект — вот сопроводительное (базовый вариант):\n\n"
                      f"✉️ {tr.cover_letter}")
        return

    a = app.analysis or {}
    head = (f"🧩 *Ассистент ({site})* — отклик делаешь сам на сайте.\n\n"
            f"🎯 *{vacancy.get('name', 'Вакансия')}*\n")
    if a.get("real_role"):
        head += f"_Роль:_ {a['real_role']}\n"
    accents = ", ".join((a.get("accents") or [])[:5])
    if accents:
        head += f"_Акценты под вакансию:_ {accents}\n"
    km = _keyword_match(vacancy, app.resume or {})
    if km:
        head += km + "\n"
    if app.review.get("verdict"):  # критик есть только в премиум-режиме (двухагентном)
        head += f"_Проверка:_ {app.review.get('verdict')} {app.review.get('score', '')}/100"
    send(chat_id, head.rstrip())
    send(chat_id, "✉️ *Сопроводительное:*\n" + (app.cover_letter or "—"))

    # Анти-галлюцинация: факты, которых нет в мастер-резюме — на ручную проверку.
    if app.warnings:
        send(chat_id, "⚠️ *Проверь перед отправкой* (мог не сверить с мастер-резюме):\n- "
             + "\n- ".join(app.warnings))

    # Резюме файлами (PDF + DOCX). Если пакетов рендера нет — отдадим текстом.
    try:
        import resume_doc  # noqa: PLC0415 — нужен fpdf2/python-docx
        with tempfile.TemporaryDirectory() as d:
            pdf, docx = resume_doc.render_both(app.resume, d)
            send_document(chat_id, pdf, "📄 Резюме под вакансию (PDF — для отправки)")
            send_document(chat_id, docx, "✏️ То же в DOCX — поправь перед отправкой при необходимости")
    except Exception as e:  # noqa: BLE001
        send(chat_id, f"⚠️ Файл резюме не собрался ({e}).\nУстанови на сервере: "
                      f"`pip install fpdf2 python-docx`.\n\n📄 Профиль резюме:\n"
                      f"{app.resume.get('profile', '')}")

    recs = app.recommendations or {}
    if recs.get("interview_questions"):
        send(chat_id, "🎯 *Возможные вопросы на интервью:*\n- "
             + "\n- ".join(recs["interview_questions"][:5]))


# --- здоровье/диагностика -----------------------------------------------------

def _build_marker() -> str:
    """Текущий коммит на сервере (хэш + дата) — видно в /health, чтобы убедиться,
    что авто-деплой подтянул свежую версию. Без git — отдаём '?'."""
    import subprocess  # noqa: PLC0415
    try:
        repo = str(Path(__file__).resolve().parent.parent)
        out = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%h · %cd", "--date=format:%Y-%m-%d %H:%M"],
            capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "?"
    except Exception:  # noqa: BLE001
        return "?"


def _health_text() -> str:
    """Что подключено: Telegram / Anthropic / HH — видно прямо в чате."""
    lines = ["🩺 *Проверка подключений*", ""]

    # Telegram — если это сообщение дошло, значит работает.
    lines.append("• Telegram: ✅ бот отвечает")

    # LLM для писем — реальный провайдер двухагентного пайплайна (career_agent).
    prov, wmodel = career_agent._writer_cfg()
    if prov == "n8n" and os.environ.get("N8N_LLM_URL"):
        model = wmodel or os.environ.get("N8N_LLM_MODEL") or "модель задаётся в n8n"
        lines.append(f"• Письма (LLM): ✅ ChatGPT через n8n ({model})")
    elif prov == "openai" and os.environ.get("OPENAI_API_KEY"):
        model = wmodel or os.environ.get("OPENAI_MODEL", tailor_mod.OPENAI_DEFAULT_MODEL)
        lines.append(f"• Письма (LLM): ✅ OpenAI {model}")
    elif prov == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        model = wmodel or os.environ.get("ANTHROPIC_MODEL", tailor_mod.DEFAULT_MODEL)
        lines.append(f"• Письма (LLM): ✅ Claude {model}")
    else:
        lines.append("• Письма (LLM): ⚠️ нет провайдера (N8N_LLM_URL / OPENAI_API_KEY / "
                     "ANTHROPIC_API_KEY) → письма по шаблону")

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

    # Фото в резюме — ставится автоматически, если сохранено.
    try:
        import resume_doc  # noqa: PLC0415
        photo = resume_doc._find_photo()
    except Exception:  # noqa: BLE001
        photo = ""
    lines.append("• Фото в резюме: ✅ сохранено, ставится автоматически" if photo
                 else "• Фото в резюме: ⚠️ не задано — пришли фото боту один раз")

    paused = "⏸ да" if apply_mod.is_paused() else "▶️ нет"
    lines.append("")
    lines.append(f"Пауза: {paused} · лимит/день: {apply_mod.daily_limit()} · "
                 f"ждут подтверждения: {len(_PENDING)}")
    lines.append(f"Сборка (деплой): {_build_marker()}")
    return "\n".join(lines)


# --- роутинг ------------------------------------------------------------------

def _handle_message(msg: dict) -> None:
    chat_id = (msg.get("chat") or {}).get("id")
    allowed = _chat_id()
    if allowed and str(chat_id) != str(allowed):
        print(f"[bot] игнор сообщения из чата {chat_id} (разрешён {allowed})", file=sys.stderr)
        return
    if _handle_photo(chat_id, msg):  # прислали фото для резюме
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/start ") and text.split(maxsplit=1)[1].strip().startswith("apply_"):
        # deep-link из подборки: t.me/Solarhh_bot?start=apply_<hh-id>
        _handle_hh(chat_id, text.split(maxsplit=1)[1].strip()[len("apply_"):])
    elif text in ("/start", "/help"):
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
    # Кнопки из подборки (шлёт n8n тем же ботом): ap: — готовь отклик по hh-id,
    # up:/dn: — обратная связь 👍/👎. И старые a:/c: — подтверждение/отмена отклика.
    if data.startswith("ap:"):
        _answer_callback(cb.get("id", ""), "Готовлю отклик…")
        _handle_hh(chat_id, data[3:])
    elif data.startswith("up:"):
        _record_feedback(data[3:], "up")
        _answer_callback(cb.get("id", ""), "👍 Учту — больше похожего")
    elif data.startswith("dn:"):
        _record_feedback(data[3:], "down")
        _answer_callback(cb.get("id", ""), "👎 Учту — меньше похожего")
    elif data.startswith("a:"):
        _answer_callback(cb.get("id", ""))
        _handle_confirm(chat_id, data[2:])
    elif data.startswith("c:"):
        _answer_callback(cb.get("id", ""))
        _PENDING.pop(data[2:], None)
        send(chat_id, "✖️ Отменено — отклик не отправлен.")
    else:
        _answer_callback(cb.get("id", ""))


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
