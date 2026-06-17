#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OAuth2-авторизация соискателя на HH (grant_type=authorization_code).

Нужна для персонального поиска и откликов (negotiations) от имени Павла.
Для простого поиска вакансий это НЕ обязательно — там хватает токена приложения
(HH_CLIENT_ID/HH_CLIENT_SECRET, см. sources.py).

Предварительно: зарегистрируй приложение на https://dev.hh.ru/admin и задай в .env:
    HH_CLIENT_ID=...
    HH_CLIENT_SECRET=...
    HH_REDIRECT_URI=...   # должен совпадать с указанным при регистрации приложения

Шаги:
    1) python3 src/hh_auth.py url           # открой ссылку, авторизуйся, скопируй code из адреса
    2) python3 src/hh_auth.py code <CODE>   # обменяет code на токены, сохранит в state/hh_token.json
    3) python3 src/hh_auth.py refresh        # обновить access_token по refresh_token

Токены пишутся в state/hh_token.json (этот каталог в .gitignore).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HH = "https://api.hh.ru"
AUTH_URL = "https://hh.ru/oauth/authorize"
STATE = Path(__file__).resolve().parent.parent / "state"
TOKEN_FILE = STATE / "hh_token.json"


def _ua() -> str:
    return os.environ.get("HH_USER_AGENT", "findwork/1.0 (sunpavel@gmail.com)")


def _need(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Не задана переменная окружения {name} (см. .env / docs/hh_api.md)")
    return val


def build_url() -> str:
    cid = _need("HH_CLIENT_ID")
    redirect = _need("HH_REDIRECT_URI")
    qs = urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": redirect,
    })
    return f"{AUTH_URL}?{qs}"


def _post_token(data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        f"{HH}/token", data=body,
        headers={"HH-User-Agent": _ua(), "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _save(tok: dict) -> None:
    STATE.mkdir(exist_ok=True)
    tok["expires_at"] = time.time() + tok.get("expires_in", 0)
    TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)


def exchange_code(code: str) -> None:
    tok = _post_token({
        "grant_type": "authorization_code",
        "client_id": _need("HH_CLIENT_ID"),
        "client_secret": _need("HH_CLIENT_SECRET"),
        "redirect_uri": _need("HH_REDIRECT_URI"),
        "code": code,
    })
    if "access_token" not in tok:
        sys.exit(f"Ошибка обмена code: {tok}")
    _save(tok)
    print(f"OK — токен соискателя сохранён в {TOKEN_FILE} (живёт ~{tok.get('expires_in', 0)//86400} дн.)")


def refresh() -> None:
    if not TOKEN_FILE.exists():
        sys.exit("Нет state/hh_token.json — сначала авторизуйся (url → code).")
    rt = json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("refresh_token")
    if not rt:
        sys.exit("В сохранённом токене нет refresh_token.")
    tok = _post_token({"grant_type": "refresh_token", "refresh_token": rt})
    if "access_token" not in tok:
        sys.exit(f"Ошибка refresh: {tok}")
    _save(tok)
    print("OK — access_token обновлён.")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "url"
    if cmd == "url":
        print("Открой эту ссылку, авторизуйся, затем скопируй параметр code из адресной строки:\n")
        print(build_url())
        print("\nПотом: python3 src/hh_auth.py code <ВСТАВЬ_CODE>")
    elif cmd == "code":
        if len(argv) < 2:
            sys.exit("Использование: python3 src/hh_auth.py code <CODE>")
        exchange_code(argv[1])
    elif cmd == "refresh":
        refresh()
    else:
        sys.exit("Команды: url | code <CODE> | refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
