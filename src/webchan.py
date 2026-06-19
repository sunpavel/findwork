#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Источник вакансий из публичных Telegram-каналов (без авторизации).

Топ-роли часто висят в профильных каналах хедхантеров, которых нет на HH. Читаем
публичную веб-витрину канала https://t.me/s/<канал> (server-rendered HTML, без API и
без MTProto), вытаскиваем посты, грубо отбираем «похоже на вакансию» и нормализуем под
общий вид вакансии — дальше их так же судит LLM по мастер-резюме (relevance_llm).

Каналы задаются списком (env TG_CHANNELS="@a,@b" или profile.locations? — см. sources).
Только stdlib. Релевантность отсеет нерелевантное на этапе скоринга/судьи.
"""

from __future__ import annotations

import html as _html
import re
import urllib.request

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/120.0 Safari/537.36")

# Пост «похож на вакансию», если содержит хотя бы один из этих маркеров и не слишком короткий.
_VAC_HINTS = ["ваканс", "ищем", "ищу", "требуется", "в команду", "зарплат", "оклад", "доход",
              "вилка", "з/п", "зп ", "we are hiring", "hiring", "ищется", "открыт набор",
              "позиц", "релокац", "remote", "удалённо", "удаленно", "оффер"]
_ROLE_HINTS = ["директор", "руководител", "head", "cmo", "cco", "cpo", "vp", "вице-президент",
               "chief", "лид", "lead", "глава"]


def _fetch(channel: str) -> str:
    url = f"https://t.me/s/{channel.lstrip('@')}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "ru,en"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def _strip(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    return _html.unescape(re.sub(r"[ \t]+", " ", t)).strip()


def parse_posts(htmltext: str) -> list[dict]:
    """Посты со страницы t.me/s/<канал>: режем по data-post (по одному на сообщение),
    из каждого берём текст, ссылку и дату — так id/текст/дата всегда выровнены."""
    out: list[dict] = []
    for chunk in htmltext.split('data-post="')[1:]:
        mid = chunk.split('"', 1)[0]                     # вид: channel/12345
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>\s*<div class="tgme_widget_message_(?:footer|info)',
                      chunk, re.S) or re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', chunk, re.S)
        text = _strip(m.group(1)) if m else ""
        dm = re.search(r'<time[^>]+datetime="([^"]+)"', chunk)
        if text:
            out.append({"id": mid, "text": text,
                        "url": f"https://t.me/{mid}", "date": dm.group(1) if dm else ""})
    return out


def _looks_like_vacancy(text: str) -> bool:
    tl = text.lower()
    if len(tl) < 120:
        return False
    return any(h in tl for h in _VAC_HINTS) and any(h in tl for h in _ROLE_HINTS)


def channel_vacancies(channels: list[str]) -> list[dict]:
    """Нормализованные вакансии из списка каналов (битый канал не роняет сбор)."""
    out: list[dict] = []
    for c in channels:
        c = c.strip()
        if not c:
            continue
        try:
            posts = parse_posts(_fetch(c))
        except Exception as e:  # noqa: BLE001
            print(f"[webchan] канал {c} не прочитан: {e}")
            continue
        for p in posts:
            if not _looks_like_vacancy(p["text"]):
                continue
            title = (p["text"].split("\n", 1)[0] or p["text"])[:120].strip()
            out.append({
                "id": "tg-" + p["id"].replace("/", "-"),
                "title": title,
                "company": "@" + c.lstrip("@"),
                "url": p["url"],
                "area": "",
                "salary": None,                 # вилку (если есть) прочитает судья из текста
                "published_at": p.get("date", ""),
                "description": p["text"][:3000],
            })
    return out


if __name__ == "__main__":
    import sys
    chans = sys.argv[1:] or ["durov"]
    posts_total = sum(len(parse_posts(_fetch(c))) for c in chans)
    vacs = channel_vacancies(chans)
    print(f"каналы: {', '.join(chans)} · постов: {posts_total} · похоже на вакансии: {len(vacs)}")
    for v in vacs[:5]:
        print(f"  — [{v['company']}] {v['title']}  {v['url']}")
