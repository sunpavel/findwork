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
from pathlib import Path
from typing import Callable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def sample_source(**_) -> list[dict]:
    """Тестовый источник: читает data/sample_vacancies.json. Для офлайн-прогона пайплайна."""
    with open(DATA_DIR / "sample_vacancies.json", encoding="utf-8") as f:
        return json.load(f)


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
    "hh": hh_source,
}


def get_source(name: str) -> Callable[..., list[dict]]:
    if name not in _REGISTRY:
        raise KeyError(f"неизвестный источник '{name}'. Доступны: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]
