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
    with urllib.request.urlopen(req, timeout=30) as resp:
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
    queries = [r["name"] for r in profile.get("target_roles", [])]
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


HH_API = "https://api.hh.ru/vacancies"


def _hh_token() -> str | None:
    """Берёт access_token: из env HH_ACCESS_TOKEN или из конфига hh-applicant-tool."""
    import os
    if os.environ.get("HH_ACCESS_TOKEN"):
        return os.environ["HH_ACCESS_TOKEN"]
    cfg = Path.home() / ".config" / "hh-applicant-tool" / "config.json"
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        tok = data.get("token") or {}
        return tok.get("access_token") or data.get("access_token")
    return None


def _hh_query(text: str, token: str, area: int = 1, per_page: int = 50) -> list[dict]:
    import os
    ua = os.environ.get("HH_USER_AGENT", "findwork/1.0 (sunpavel@gmail.com)")
    qs = urllib.parse.urlencode({"text": text, "area": area, "per_page": per_page, "page": 0})
    req = urllib.request.Request(
        f"{HH_API}?{qs}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": ua, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
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


def hh_source(profile: dict, **_) -> list[dict]:
    """Боевой источник HH (СЕРЫЙ путь).

    ⚠️ Публичный API HH для соискателей закрыт (15.12.2025). Рабочий путь — токен
    официального Android-приложения, который выдаёт `hh-applicant-tool authorize`
    (запускается на VPS в РФ; см. docs/vps_setup.md). Поиск идёт по api.hh.ru с этим
    токеном и app-User-Agent.

    Если токена нет (не авторизован) — поднимаем исключение; пайплайн его поймает и
    просто пропустит HH-источник, не падая.
    """
    token = _hh_token()
    if not token:
        raise RuntimeError("нет токена HH — выполни `hh-applicant-tool authorize` на VPS "
                           "или задай HH_ACCESS_TOKEN (см. docs/vps_setup.md)")
    area = (profile.get("locations") or {}).get("hh_area_ids", [1])[0]
    queries = [r["name"] for r in profile.get("target_roles", [])]
    seen, result = set(), []
    for q in dict.fromkeys(queries):
        try:
            for vac in _hh_query(q, token, area=area):
                if vac["id"] not in seen:
                    seen.add(vac["id"])
                    result.append(vac)
        except Exception as e:  # noqa: BLE001
            print(f"[hh] запрос '{q}' не удался: {e}")
    return result


_REGISTRY: dict[str, Callable[..., list[dict]]] = {
    "sample": sample_source,
    "trudvsem": trudvsem_source,
    "hh": hh_source,
}


def get_source(name: str) -> Callable[..., list[dict]]:
    if name not in _REGISTRY:
        raise KeyError(f"неизвестный источник '{name}'. Доступны: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]
