#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Клиент HH через эмуляцию официального мобильного приложения.

Зачем отдельно от sources.py: официальный dev-API (токен приложения/соискателя из
dev.hh.ru) ПОЗВОЛЯЕТ искать и читать вакансии, но РЕЖЕТ создание/правку резюме
(`/resumes/*`) и отклики (`/negotiations`) — мы это проверили (403). Доступ к этим
действиям даёт только токен официального мобильного приложения HH. Этот модуль
работает именно от его имени (как `hh-applicant-tool`).

⚠️ Это «серый» путь: формально нарушает ToS HH и несёт риск блокировки аккаунта.
Используется осознанно, под личный поиск, с вежливыми лимитами и паузами.
Источник авторизации — НЕ в репозитории.

Откуда берётся токен приложения (в порядке приоритета):
  1) переменная окружения HH_APP_ACCESS_TOKEN;
  2) state/hh_app_token.json (наш формат: {"access_token": ..., "refresh_token": ...});
  3) состояние hh-applicant-tool (если он установлен и авторизован) —
     путь задаётся HH_APP_TOOL_STATE или берётся из ~/.config/hh-applicant-tool/.

Рекомендуемый способ получить токен — один раз авторизоваться зрелым инструментом
`hh-applicant-tool` (он реализует OAuth официального приложения и хранит токен),
после чего этот модуль переиспользует токен. См. docs/auto_apply.md.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HH_API_BASE = "https://api.hh.ru"
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
APP_TOKEN_FILE = STATE_DIR / "hh_app_token.json"

# OAuth-эндпоинт официального приложения. client_id/secret приложения публично
# известны (их использует hh-applicant-tool); задаются через окружение, чтобы не
# зашивать секреты в репозиторий. Нужны только для refresh нашего собственного токена.
OAUTH_TOKEN_URL = f"{HH_API_BASE}/token"


class HHAppError(RuntimeError):
    """Ошибка обращения к HH от имени приложения (с кодом и телом ответа)."""

    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _user_agent() -> str:
    # По умолчанию мимикрируем под мобильное приложение (как делает hh-applicant-tool).
    return os.environ.get("HH_APP_USER_AGENT", "ru.hh.android/7.0, Device: findwork, Android OS: 14")


def _tool_state_token() -> str | None:
    """Пробуем прочитать токен из состояния hh-applicant-tool, если он есть."""
    candidates = []
    if os.environ.get("HH_APP_TOOL_STATE"):
        candidates.append(Path(os.environ["HH_APP_TOOL_STATE"]))
    home = Path.home()
    candidates += [
        home / ".config" / "hh-applicant-tool" / "state.json",
        home / ".config" / "hh-applicant-tool" / "token.json",
    ]
    for path in candidates:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # hh-applicant-tool хранит токен либо плоско, либо во вложенном объекте.
                tok = data.get("access_token") or (data.get("token") or {}).get("access_token")
                if tok:
                    return tok
        except Exception:  # noqa: BLE001 — чужой формат не должен ронять нас
            continue
    return None


def _load_app_token() -> dict | None:
    if APP_TOKEN_FILE.exists():
        try:
            return json.loads(APP_TOKEN_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def _save_app_token(tok: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    if "expires_in" in tok:
        tok["expires_at"] = time.time() + tok.get("expires_in", 0)
    APP_TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(APP_TOKEN_FILE, 0o600)


def _refresh_app_token(refresh_token: str) -> str:
    """Обновляем access_token приложения по refresh_token (если заданы app-креды)."""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(
        OAUTH_TOKEN_URL, data=body,
        headers={"HH-User-Agent": _user_agent(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        tok = json.loads(resp.read().decode("utf-8"))
    if "access_token" not in tok:
        raise HHAppError(f"refresh приложения не вернул access_token: {tok}")
    _save_app_token(tok)
    return tok["access_token"]


def get_app_token() -> str:
    """Возвращает действующий токен приложения; при необходимости обновляет его."""
    if os.environ.get("HH_APP_ACCESS_TOKEN"):
        return os.environ["HH_APP_ACCESS_TOKEN"]

    saved = _load_app_token()
    if saved and saved.get("access_token"):
        # Если токен скоро истечёт и есть refresh — обновим.
        if saved.get("expires_at", float("inf")) <= time.time() + 120 and saved.get("refresh_token"):
            try:
                return _refresh_app_token(saved["refresh_token"])
            except Exception:  # noqa: BLE001 — отдаём что есть, пусть упадёт на запросе
                pass
        return saved["access_token"]

    tool_tok = _tool_state_token()
    if tool_tok:
        return tool_tok

    raise HHAppError(
        "нет токена приложения HH. Авторизуйся через hh-applicant-tool "
        "(`hh-applicant-tool authorize`) или задай HH_APP_ACCESS_TOKEN. "
        "Подробности — docs/auto_apply.md")


def _request(method: str, path: str, *, params: dict | None = None,
             payload: dict | None = None) -> dict:
    """Запрос к HH от имени приложения. Возвращает разобранный JSON (или {})."""
    token = get_app_token()
    url = f"{HH_API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "HH-User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HHAppError(f"{method} {path} → HTTP {e.code}", status=e.code, body=body) from e
    except urllib.error.URLError as e:
        raise HHAppError(f"{method} {path} → сеть: {e.reason}") from e


# --- Высокоуровневые операции ------------------------------------------------

def parse_vacancy_id(url_or_id: str) -> str:
    """Достаёт числовой id вакансии из ссылки hh.ru или принимает голый id."""
    s = (url_or_id or "").strip()
    if s.isdigit():
        return s
    # https://hh.ru/vacancy/12345678?... или .../vacancy/12345678/
    import re
    m = re.search(r"/vacancy/(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"vacancyId=(\d+)", s)
    if m:
        return m.group(1)
    raise HHAppError(f"не удалось извлечь id вакансии из «{url_or_id}»")


def get_vacancy(vacancy_id: str) -> dict:
    """Полное описание вакансии (GET /vacancies/{id})."""
    return _request("GET", f"/vacancies/{parse_vacancy_id(vacancy_id)}")


def list_resumes() -> list[dict]:
    """Резюме соискателя (GET /resumes/mine)."""
    return _request("GET", "/resumes/mine").get("items", [])


def get_resume(resume_id: str) -> dict:
    """Полный объект резюме (GET /resumes/{id}) — основа для клонирования/правки."""
    return _request("GET", f"/resumes/{resume_id}")


# Поля резюме, которые HH вычисляет сам и которые нельзя слать при создании/правке.
_RESUME_READONLY = {
    "id", "created_at", "updated_at", "alternate_url", "url", "download",
    "views_url", "status", "finished", "blocked", "access", "actions",
    "negotiations_history", "moderation_note", "total_views", "new_views",
    "similar_vacancies_url", "can_publish_or_update", "next_publish_at",
    "publish_url", "viewed_by", "approved", "valued",
}


def _clean_resume_payload(resume: dict) -> dict:
    """Убирает read-only поля, оставляя только то, что HH принимает на запись."""
    return {k: v for k, v in resume.items() if k not in _RESUME_READONLY}


def update_resume(resume_id: str, overrides: dict) -> None:
    """Обновляет существующее резюме (PUT /resumes/{id}). Берём текущий объект,
    накладываем overrides, отправляем. Так не теряем обязательные поля."""
    base = get_resume(resume_id)
    payload = _clean_resume_payload(base)
    payload.update(overrides)
    _request("PUT", f"/resumes/{resume_id}", payload=payload)


def clone_resume(base_resume_id: str, overrides: dict) -> str:
    """Создаёт НОВОЕ резюме на основе существующего (POST /resumes) с правками.

    HH отдаёт id нового резюме в заголовке `Location: /resumes/{id}` — берём его.
    Фолбэк (если заголовка нет): перечитываем список и берём самое свежее.
    """
    base = get_resume(base_resume_id)
    payload = _clean_resume_payload(base)
    payload.update(overrides)

    token = get_app_token()
    req = urllib.request.Request(
        f"{HH_API_BASE}/resumes", data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "HH-User-Agent": _user_agent(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            location = resp.headers.get("Location", "")
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HHAppError(f"POST /resumes → HTTP {e.code}", status=e.code, body=body) from e
    except urllib.error.URLError as e:
        raise HHAppError(f"POST /resumes → сеть: {e.reason}") from e

    import re
    m = re.search(r"/resumes/([0-9a-zA-Z]+)", location)
    if m:
        return m.group(1)
    # Фолбэк: самое свежее среди наших резюме.
    items = list_resumes()
    if not items:
        raise HHAppError("резюме создано, но id не получен (нет Location и пуст /resumes/mine)")
    return max(items, key=lambda r: r.get("updated_at", ""))["id"]


def apply_to_vacancy(vacancy_id: str, resume_id: str, message: str) -> None:
    """Отклик на вакансию (POST /negotiations): резюме + сопроводительное.

    HH ждёт form-urlencoded для этого эндпоинта, а не JSON.
    """
    vid = parse_vacancy_id(vacancy_id)
    token = get_app_token()
    body = urllib.parse.urlencode({
        "vacancy_id": vid,
        "resume_id": resume_id,
        "message": message or "",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{HH_API_BASE}/negotiations", data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "HH-User-Agent": _user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        raise HHAppError(f"POST /negotiations → HTTP {e.code}", status=e.code, body=body_txt) from e
    except urllib.error.URLError as e:
        raise HHAppError(f"POST /negotiations → сеть: {e.reason}") from e


def whoami() -> dict:
    """Профиль авторизованного соискателя (GET /me) — для проверки токена."""
    return _request("GET", "/me")


if __name__ == "__main__":
    # Утилита самопроверки: `python3 src/hh_app.py [vacancy_url_or_id]`
    import sys
    try:
        me = whoami()
        print(f"OK — авторизован как: {me.get('first_name', '')} {me.get('last_name', '')} "
              f"(id {me.get('id', '?')})")
        resumes = list_resumes()
        print(f"Резюме: {len(resumes)}")
        for r in resumes:
            print(f"  • {r.get('id')}  «{r.get('title', '—')}»  [{r.get('status', {}).get('name', '?')}]")
        if len(sys.argv) > 1:
            v = get_vacancy(sys.argv[1])
            print(f"\nВакансия {v.get('id')}: {v.get('name')} — "
                  f"{(v.get('employer') or {}).get('name', '?')}")
    except HHAppError as e:
        print(f"Ошибка: {e}")
        if e.body:
            print(e.body[:500])
        raise SystemExit(1)
