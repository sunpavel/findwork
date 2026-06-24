#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Источники вакансий. Единый интерфейс: функция возвращает список словарей-вакансий
нормализованного вида:

  {
    "id": str,                # уникальный id (для дедупа)
    "title": str,
    "company": str,
    "url": str,
    "area": str,
    "salary": {"from": int|None, "to": int|None, "currency": str} | None,
    "published_at": str,      # ISO
    "description": str,
  }

Источники подключаются по имени через get_source(name). Так пайплайн не зависит
от того, откуда пришли вакансии (HH / парсер / Telegram-каналы / getmatch / ...).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def sample_source(**_) -> list[dict]:
    """Тестовый источник: читает data/sample_vacancies.json. Для офлайн-прогона пайплайна."""
    with open(DATA_DIR / "sample_vacancies.json", encoding="utf-8") as f:
        return json.load(f)


TRUDVSEM_API = "http://opendata.trudvsem.ru/api/v1/vacancies"


def _trudvsem_query(text: str, limit: int = 100) -> list[dict]:
    """Один запрос к официальному открытому API «Работа России» (Trudvsem)."""
    qs = urllib.parse.urlencode({"text": text, "limit": limit})
    req = urllib.request.Request(f"{TRUDVSEM_API}?{qs}", headers={"Accept": "application/json"})
    with _hh_urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    items = (payload.get("results") or {}).get("vacancies") or []
    out = []
    for it in items:
        v = it.get("vacancy", {})
        desc = " ".join(filter(None, [
            v.get("duty", ""), v.get("requirements", ""), v.get("qualification", ""),
            (v.get("category") or {}).get("specialisation", ""),
        ]))
        out.append({
            "id": f"trudvsem-{v.get('id')}",
            "title": v.get("job-name", ""),
            "company": (v.get("company") or {}).get("name", ""),
            "url": v.get("vac_url", ""),
            "area": (v.get("region") or {}).get("name", ""),
            "salary": {
                "from": v.get("salary_min"),
                "to": v.get("salary_max"),
                "currency": v.get("currency") or "RUR",
            },
            "published_at": v.get("creation-date", ""),
            "description": desc.strip(),
        })
    return out


def trudvsem_source(profile: dict, limit_per_query: int = 100, **_) -> list[dict]:
    """Боевой ЛЕГАЛЬНЫЙ источник: официальное открытое API «Работа России».

    Бесплатно, без авторизации и без обхода чего-либо. Ищем по названиям целевых
    ролей, агрегируем и дедупим по id. Релевантность отсеет нерелевантное в скоринге.
    """
    queries = profile.get("search_queries") or [r["name"] for r in profile.get("target_roles", [])]
    queries += ["директор по маркетингу", "коммерческий директор"]
    seen, result = set(), []
    for q in dict.fromkeys(queries):  # уникальные, сохраняя порядок
        try:
            for vac in _trudvsem_query(q, limit_per_query):
                if vac["id"] not in seen:
                    seen.add(vac["id"])
                    result.append(vac)
        except Exception as e:  # noqa: BLE001 — один битый запрос не должен ронять сбор
            print(f"[trudvsem] запрос '{q}' не удался: {e}")
    return result


HH_API_BASE = "https://api.hh.ru"
STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def _hh_user_agent() -> str:
    import os
    return os.environ.get("HH_USER_AGENT", "findwork/1.0 (sunpavel@gmail.com)")


def _hh_urlopen(req, timeout: int = 30):
    """urlopen для запросов к HH с поддержкой HH_PROXY.

    HH банит дата-центровые IP через DDoS-Guard (403 forbidden ещё ДО API, server: ddos-guard).
    HH_PROXY (http/https-прокси в стране без бана — жилой/РФ) даёт обходной путь ТОЛЬКО для HH,
    не трогая остальной трафик (n8n/LLM/Telegram). Без переменной — обычный urlopen (он и так
    уважает HTTPS_PROXY/HTTP_PROXY из окружения)."""
    import os
    proxy = os.environ.get("HH_PROXY")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _hh_app_token() -> str | None:
    """Токен ПРИЛОЖЕНИЯ (grant_type=client_credentials) — для поиска вакансий без логина.
    Полностью официально. Нужны HH_CLIENT_ID/HH_CLIENT_SECRET из https://dev.hh.ru/admin.
    Кэшируем в state/hh_app_token.json до истечения."""
    import os
    import time
    cid, secret = os.environ.get("HH_CLIENT_ID"), os.environ.get("HH_CLIENT_SECRET")
    if not (cid and secret):
        return None
    cache = STATE_DIR / "hh_app_token.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("expires_at", 0) > time.time() + 60:
            return data.get("access_token")
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
    }).encode()
    req = urllib.request.Request(
        f"{HH_API_BASE}/token", data=body,
        headers={"HH-User-Agent": _hh_user_agent(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    with _hh_urlopen(req, timeout=30) as resp:
        tok = json.loads(resp.read().decode("utf-8"))
    STATE_DIR.mkdir(exist_ok=True)
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600)
    cache.write_text(json.dumps(tok), encoding="utf-8")
    return tok.get("access_token")


def _hh_user_token() -> str | None:
    """Токен СОИСКАТЕЛЯ (authorization_code) — для персонального поиска и откликов.
    Из env HH_ACCESS_TOKEN или из state/hh_token.json (см. src/hh_auth.py)."""
    import os
    if os.environ.get("HH_ACCESS_TOKEN"):
        return os.environ["HH_ACCESS_TOKEN"]
    tf = STATE_DIR / "hh_token.json"
    if tf.exists():
        return json.loads(tf.read_text(encoding="utf-8")).get("access_token")
    return None


def _hh_token() -> str:
    """Приоритет: токен соискателя (персональный поиск + отклики) → токен приложения (поиск)."""
    tok = _hh_user_token() or _hh_app_token()
    if not tok:
        raise RuntimeError(
            "нет токена HH. Для поиска: зарегистрируй приложение на https://dev.hh.ru/admin и "
            "задай HH_CLIENT_ID/HH_CLIENT_SECRET в .env. Для откликов/персонального поиска: "
            "авторизуйся `python3 src/hh_auth.py`. См. docs/hh_api.md")
    return tok


def _hh_query(text: str, token: str, area: int = 1, per_page: int = 100,
              date_from: str | None = None, search_field: str = "name",
              order_by: str = "publication_time") -> list[dict]:
    """Поиск по GET /vacancies согласно официальной спецификации.

    Параметры подобраны осознанно (см. docs/hh_api.md):
      • search_field=name  — ищем роль в НАЗВАНИИ вакансии (точнее, без мусора из тела);
      • area               — регион (1 = Москва; задаётся в profile.locations.hh_area_ids);
      • only_with_salary=false — не отсекаем вакансии без вилки (директорские часто без неё),
                                 зарплату оценивает скоринг;
      • order_by=publication_time — сначала свежие;
      • date_from          — только вакансии не старше даты (для утреннего «нового»);
      • per_page=100       — максимум на страницу.
    """
    params = {
        "text": text,
        "search_field": search_field,
        "area": area,  # int или список регионов (Москва=1, МО=113, СПб=2019)
        "only_with_salary": "false",
        "order_by": order_by,
        "per_page": per_page,
        "page": 0,
    }
    if date_from:
        params["date_from"] = date_from
    qs = urllib.parse.urlencode(params, doseq=True)  # doseq — чтобы список area дал area=1&area=113…
    req = urllib.request.Request(
        f"{HH_API_BASE}/vacancies?{qs}",
        headers={"Authorization": f"Bearer {token}", "HH-User-Agent": _hh_user_agent(),
                 "Accept": "application/json"})
    with _hh_urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out = []
    for v in payload.get("items", []):
        sn = v.get("snippet") or {}
        sal = v.get("salary") or {}
        out.append({
            "id": f"hh-{v.get('id')}",
            "title": v.get("name", ""),
            "company": (v.get("employer") or {}).get("name", ""),
            "url": v.get("alternate_url", ""),
            "area": (v.get("area") or {}).get("name", ""),
            "salary": {"from": sal.get("from"), "to": sal.get("to"),
                       "currency": sal.get("currency") or "RUR"} if sal else None,
            "published_at": v.get("published_at", ""),
            "description": " ".join(filter(None, [sn.get("requirement"), sn.get("responsibility")])),
        })
    return out


def hh_source(profile: dict, since_days: int = 2, **_) -> list[dict]:
    """Боевой источник HH через ОФИЦИАЛЬНЫЙ API (OAuth2).

    Легально: своё приложение на dev.hh.ru → токен соискателя (приоритет) или приложения.
    Запрос строится по спецификации: поиск роли в названии, регион из профиля, свежие
    вакансии за последние `since_days` дней (дедуп в пайплайне убирает уже виденные).

    По городу: area берётся из profile.locations.hh_area_ids (1 = Москва). Формат «неважно» →
    при необходимости добавим удалёнку через work_format (id из справочника) отдельной веткой.
    """
    import datetime as _dt
    token = _hh_token()
    area = (profile.get("locations") or {}).get("hh_area_ids") or [1]  # все регионы профиля (не только Москва)
    date_from = (_dt.date.today() - _dt.timedelta(days=since_days)).strftime("%Y-%m-%dT00:00:00")
    queries = profile.get("search_queries") or [r["name"] for r in profile.get("target_roles", [])]
    seen, result = set(), []
    for q in dict.fromkeys(queries):
        try:
            for vac in _hh_query(q, token, area=area, date_from=date_from):
                if vac["id"] not in seen:
                    seen.add(vac["id"])
                    result.append(vac)
        except Exception as e:  # noqa: BLE001
            print(f"[hh] запрос '{q}' не удался: {e}")
    return result


# Проверенные публичные каналы с вакансиями уровня кандидата (коммерческий директор/CCO,
# директор по маркетингу/CMO, руководитель/C-level). Отобраны скрейпом t.me/s/ по реальной
# плотности директорских/коммерческих/маркетинговых вакансий (см. webchan.py). Это дефолт —
# переопределяется env TG_CHANNELS="@a,@b". Нерелевантные посты отсеет LLM-судья по резюме.
DEFAULT_TG_CHANNELS = [
    "vacanciesrus",   # директора по маркетингу/CMO, Head of Growth, коммерч. директора
    "finexecutive",   # управляющие/коммерческие директора, C-level (финансы/IT/консалтинг)
    "theypaywell",    # руководители/директора с доходом >100к
    "marketing_jobs", # маркетинг/бренд/директор по маркетингу, в основном Москва
    "marketing_job",  # Marketing.job — много вакансий, есть «Директор по маркетингу»/Growth (проверено)
    "careerspace",    # senior-доска (Mars/лиды/директора), высокий объём (проверено)
    "perezvonyu",     # digital/PR/маркетинг с контактами работодателей, Москва
    "prwork",         # PR/маркетинг senior (зам. PR-директора и т.п.)
    "morejobs",       # руководящие позиции в маркетинге/коммерции
]


def tgchannels_source(profile: dict, **_) -> list[dict]:
    """Вакансии из публичных Telegram-каналов (см. src/webchan.py).

    Каналы: env TG_CHANNELS="@a,@b" — если задан, иначе проверенный DEFAULT_TG_CHANNELS
    (директор по маркетингу/CMO, коммерческий директор/CCO, C-level). Релевантность по
    резюме (CCO/CMO) отсеет нерелевантное в скоринге."""
    import os  # noqa: PLC0415
    import webchan  # noqa: PLC0415
    env = [c.strip() for c in os.environ.get("TG_CHANNELS", "").split(",") if c.strip()]
    channels = env or DEFAULT_TG_CHANNELS
    return webchan.channel_vacancies(channels)


_REGISTRY: dict[str, Callable[..., list[dict]]] = {
    "sample": sample_source,
    "trudvsem": trudvsem_source,
    "hh": hh_source,
    "tgchannels": tgchannels_source,
}


def get_source(name: str) -> Callable[..., list[dict]]:
    if name not in _REGISTRY:
        raise KeyError(f"неизвестный источник '{name}'. Доступны: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]
