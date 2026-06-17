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


def hh_source(profile: dict, **_) -> list[dict]:
    """Боевой источник HH.

    ⚠️ Публичный API HH для соискателей закрыт (15.12.2025). Прямой api.hh.ru → 403.
    Рабочий путь — эмуляция официального Android-приложения HH (как в утилите
    `s3rgeym/hh-applicant-tool`), запускаемая с резидентного/российского IP (VPS в РФ).

    План подключения (выполняется на VPS, где есть авторизация в HH):
      1) pip install hh-applicant-tool
      2) hh-applicant-tool authorize        # один раз, OAuth официального приложения
      3) здесь — вызвать поиск через токен приложения и нормализовать ответ под схему выше.

    Параметры поиска берём из profile['target_roles'] и profile['locations'].
    Реализуется после поднятия VPS и авторизации (см. docs/vps_setup.md).
    """
    raise NotImplementedError(
        "HH-источник подключается на VPS после авторизации (см. docstring и docs/vps_setup.md)."
    )


_REGISTRY: dict[str, Callable[..., list[dict]]] = {
    "sample": sample_source,
    "trudvsem": trudvsem_source,
    "hh": hh_source,
}


def get_source(name: str) -> Callable[..., list[dict]]:
    if name not in _REGISTRY:
        raise KeyError(f"неизвестный источник '{name}'. Доступны: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]
