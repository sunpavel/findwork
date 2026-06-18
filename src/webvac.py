#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный фетчер вакансий с публичных страниц (facancy.ru и прочие сайты).

Зачем: для НЕ-HH площадок (например, facancy.ru) авто-отклик невозможен — там бот
работает в режиме «ассистент»: достаёт текст вакансии со страницы, генерит резюме и
сопроводительное и присылает их тебе в Telegram. Отклик ты делаешь сам на сайте.

Возвращает словарь в том же виде, что и вакансия HH (понимает tailor.py):
  {"name", "employer": {"name"}, "area": {"name"}, "description", "key_skills": []}

Только стандартная библиотека. Парсинг намеренно «достаточный»: og-метатеги +
очистка видимого текста. Если структура сайта незнакомая — отдаём что смогли, плюс
есть фолбэк: можно прислать боту текст вакансии напрямую (см. from_text).
"""

from __future__ import annotations

import html
import json
import re
import urllib.request

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch_html(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _meta(html_text: str, prop: str) -> str:
    """Достаёт content из <meta property/name=prop ...> (og:title и т.п.)."""
    for attr in ("property", "name"):
        m = re.search(
            rf'<meta[^>]+{attr}=["\']{re.escape(prop)}["\'][^>]*content=["\'](.*?)["\']',
            html_text, flags=re.I | re.S)
        if not m:
            m = re.search(
                rf'<meta[^>]+content=["\'](.*?)["\'][^>]*{attr}=["\']{re.escape(prop)}["\']',
                html_text, flags=re.I | re.S)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _visible_text(html_text: str) -> str:
    """Грубо вырезает скрипты/стили/теги и возвращает видимый текст."""
    s = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text, flags=re.I | re.S)
    s = re.sub(r"<(br|/p|/li|/div|/h\d|/tr)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "• ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _jsonld_jobposting(html_text: str) -> dict:
    """Ищет на странице разметку schema.org JobPosting (application/ld+json).

    Большинство job-сайтов кладут туда название, работодателя, описание и регион —
    это куда надёжнее, чем гадать по тегам.
    """
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                         html_text, flags=re.I | re.S):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001 — кривой JSON на странице не должен ронять нас
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                stack.extend(node["@graph"])
            if "JobPosting" in str(node.get("@type", "")):
                return node
    return {}


def fetch_vacancy(url: str, max_chars: int = 6000) -> dict:
    """Скачивает страницу вакансии и собирает словарь в формате, понятном tailor.py."""
    page = _fetch_html(url)
    job = _jsonld_jobposting(page)

    name = (job.get("title") or "").strip() or _meta(page, "og:title")
    if not name:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
        name = html.unescape(m.group(1)).strip() if m else "Вакансия"
    name = re.sub(r"\s*[|–—-]\s*(facancy|hh\.ru|вакансия).*$", "", name, flags=re.I).strip()

    org = job.get("hiringOrganization")
    employer = (org.get("name", "") if isinstance(org, dict) else "").strip() \
        or _meta(page, "og:site_name")

    loc = job.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    area = ""
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            area = addr.get("addressLocality", "") or addr.get("addressRegion", "")

    # Описание: из JobPosting (часто HTML) → og → видимый текст страницы.
    desc = _visible_text(job["description"]) if job.get("description") else ""
    if len(desc) < 200:
        desc = desc or _meta(page, "og:description")
        body = _visible_text(page)
        if len(body) > len(desc):
            desc = body
    desc = desc[:max_chars].strip()

    return {
        "name": name,
        "employer": {"name": employer},
        "area": {"name": area},
        "description": desc,
        "key_skills": [],
        "source_url": url,
    }


def from_text(text: str, max_chars: int = 6000) -> dict:
    """Фолбэк: построить вакансию из присланного текста (первая строка — заголовок)."""
    text = text.strip()
    first = text.splitlines()[0] if text else "Вакансия"
    return {
        "name": first[:120],
        "employer": {"name": ""},
        "area": {"name": ""},
        "description": text[:max_chars],
        "key_skills": [],
        "source_url": "",
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Использование: python3 src/webvac.py <url>")
    v = fetch_vacancy(sys.argv[1])
    print("Название:", v["name"])
    print("Компания:", v["employer"]["name"] or "—")
    print("Описание (фрагмент):\n", v["description"][:600])
