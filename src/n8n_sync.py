#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пуш истории откликов HH в n8n — чтобы живой дайджест не показывал уже-откликнутые.

Живой дайджест — это n8n-воркфлоу: он ищет вакансии токеном ПРИЛОЖЕНИЯ и личные отклики
соискателя не видит. Бот же логинится на HH как соискатель (он и откликается), поэтому
именно он знает историю откликов. Бот периодически и сразу после каждого отклика шлёт
список hh-id откликнутых на вебхук n8n; воркфлоу кладёт их в staticData, а узел score+dedup
исключает их из дайджеста.

Конфиг:
  N8N_APPLIED_URL   = https://<n8n>/webhook/findwork-applied   (без него пуш не делается)
  N8N_APPLIED_TOKEN = общий секрет (опц.) — шлём в заголовке X-Findwork-Token

Контракт: POST JSON {"applied_ids": ["123","456", ...]} (сырые hh-id).
"""

from __future__ import annotations

import json
import os
import urllib.request

import hh_app


def push_applied(url: str | None = None, *, timeout: int = 30) -> int | None:
    """Шлёт текущую историю откликов HH в n8n. Возвращает число отправленных id;
    None — если вебхук не настроен (N8N_APPLIED_URL пуст). Исключения — наверх."""
    url = (url or os.environ.get("N8N_APPLIED_URL", "")).strip()
    if not url:
        return None
    ids = sorted(hh_app.applied_vacancy_ids())
    data = json.dumps({"applied_ids": ids}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("N8N_APPLIED_TOKEN", "").strip()
    if token:
        headers["X-Findwork-Token"] = token
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    return len(ids)


if __name__ == "__main__":
    try:
        n = push_applied()
        print("вебхук не настроен (N8N_APPLIED_URL пуст)" if n is None
              else f"отправлено откликнутых id: {n}")
    except Exception as e:  # noqa: BLE001
        print(f"ошибка пуша: {e}")
