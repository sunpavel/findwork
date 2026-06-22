#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Детерминированная проверка отклика поверх LLM (без обращения к сети).

Две задачи, обе из лучших практик рынка (Jobscan + анти-галлюцинация):
  1) ФАКТИЧНОСТЬ — числовые метрики и компании в резюме/письме должны существовать
     в мастер-резюме. Что не подтверждается — отдаём как предупреждение «проверь
     перед отправкой» (а не молча отправляем выдумку).
  2) ATS-СООТВЕТСТВИЕ — какие ключевые навыки вакансии отражены в адаптированном
     резюме; какие требования вакансии подтверждаются мастером, но НЕ всплыли
     в резюме (их можно безопасно дотянуть — это не выдумка, мы их реально имеем).

Чистый stdlib (re) — никаких зависимостей, чтобы можно было звать из bot и
career_agent в любом окружении.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"\w+", re.U)


def _sig_words(s: str) -> list[str]:
    """Значимые слова (длиннее 3 символов) — для нестрогого сопоставления навыков/компаний."""
    return [w for w in _WORD.findall((s or "").lower()) if len(w) > 3]


def mentions(needle: str, hay: str) -> bool:
    """Упоминается ли навык/фраза в тексте: по любому значимому слову (нестрого).

    «Управление командой» считается отражённым, если в тексте есть «команд…» или
    «управл…» — это снижает ложные «не отражено» при перефразировке."""
    ws = _sig_words(needle)
    return any(w in hay for w in ws) if ws else (needle or "").lower() in hay


def resume_text(resume: dict) -> str:
    """Плоский текст резюме (все смысловые поля) для матчинга навыков/фактов."""
    parts: list[str] = [resume.get("profile", "") or "", resume.get("skills", "") or ""]
    for key in ("competencies", "tools", "additional", "skill_set"):
        parts += resume.get(key, []) or []
    for e in resume.get("experience", []) or []:
        parts.append(e.get("context", "") or "")
        parts += e.get("responsibilities", []) or []
        parts += e.get("achievements", []) or []
    return " ".join(p for p in parts if p)


# --- Числовые метрики (анти-галлюцинация) ------------------------------------

def _num_key(raw: str) -> str | None:
    """Канонизирует число: убирает пробелы-разделители, '.' как тысячи, ',' как дробь."""
    s = (raw or "").strip().lstrip("+-").replace(" ", "").replace(" ", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return "%g" % float(s)
    except ValueError:
        return None


_PCT = re.compile(r"([+\-]?\d[\d  .,]*)\s*%")
_MONEY = re.compile(r"(\d[\d  .,]*)\s*(млрд|млн|тыс)\b")
_RUB = re.compile(r"(\d[\d  .,]*)\s*(?:₽|руб)")
_MULT = re.compile(r"(?:в\s+)?(\d[\d.,]*)\s*раз")
_XMULT = re.compile(r"[x×](\d[\d.,]*)")          # ×8 / x8 — тот же смысл, что «в 8 раз»
_TOP = re.compile(r"топ[-\s]?(\d+)")             # Топ-5 — сильная метрика позиционирования
# Стаж/возраст: 1–2 значные числа + «лет/год…» (любой падеж: годами, годов, году).
# Ограничение в 2 цифры отсекает календарные годы («в 2020 году» — не метрика стажа).
_YEARS = re.compile(r"(\d{1,2})\+?\s*(?:лет|год\w*)")
_COUNT = re.compile(r"(\d+)\s*(объект|комплекс|город|регион|филиал|сотрудник|человек|магазин|точк|бренд|продукт)")
# Синонимы единиц при сверке чисел: точки сети (объект/комплекс/точка/магазин/филиал) и люди —
# чтобы «15 объектов» в письме совпадало с «15 комплексов» в мастере (одно и то же), а не уезжало
# в ложный флаг «не нашёл в мастере».
_COUNT_UNIT = {"объект": "точка", "комплекс": "точка", "точк": "точка",
               "магазин": "точка", "филиал": "точка", "сотрудник": "человек"}


def claims(text: str) -> dict[tuple[str, str], str]:
    """Извлекает числовые утверждения {(число, единица): исходная подстрока}."""
    t = (text or "").lower()
    out: dict[tuple[str, str], str] = {}

    def add(num_raw: str, unit: str, orig: str) -> None:
        k = _num_key(num_raw)
        if k:
            out.setdefault((k, unit), orig.strip())

    for m in _PCT.finditer(t):
        add(m.group(1), "%", m.group(0))
    for m in _MONEY.finditer(t):
        add(m.group(1), m.group(2), m.group(0))
    for m in _RUB.finditer(t):
        add(m.group(1), "₽", m.group(0))
    for m in _MULT.finditer(t):
        add(m.group(1), "раз", m.group(0))
    for m in _XMULT.finditer(t):
        add(m.group(1), "раз", m.group(0))
    for m in _TOP.finditer(t):
        add(m.group(1), "топ", m.group(0))
    for m in _YEARS.finditer(t):
        add(m.group(1), "лет", m.group(0))
    for m in _COUNT.finditer(t):
        add(m.group(1), _COUNT_UNIT.get(m.group(2), m.group(2)), m.group(0))
    return out


def figures_to_check(cover_letter: str, resume: dict, master_md: str, limit: int = 8) -> list[str]:
    """Числа из письма/резюме, которых НЕТ в мастер-резюме (кандидаты на выдумку)."""
    found: dict[tuple[str, str], str] = {}
    found.update(claims(cover_letter))
    found.update(claims(resume_text(resume)))
    master_keys = set(claims(master_md).keys())
    res: list[str] = []
    for key, orig in found.items():
        if key not in master_keys and orig not in res:
            res.append(orig)
    return res[:limit]


def letter_metrics(cover_letter: str, master_md: str) -> list[str]:
    """Числовые метрики письма, ПОДТВЕРЖДЁННЫЕ мастер-резюме (полезная конкретика).

    Зеркало figures_to_check: там — числа-выдумки (которых нет в мастере), здесь наоборот —
    «хорошие» числа, взятые из мастер-резюме. Если их мало, письмо водянистое и нужна
    дотяжка конкретикой (см. career_agent._qa_pass)."""
    master_keys = set(claims(master_md).keys())
    out: list[str] = []
    for key, orig in claims(cover_letter).items():
        if key in master_keys and orig not in out:
            out.append(orig)
    return out


def unknown_companies(resume: dict, master_md: str, limit: int = 6) -> list[str]:
    """Компании из опыта, которых нет в мастер-резюме (ни одно значимое слово не совпало)."""
    ml = (master_md or "").lower()
    res: list[str] = []
    for e in resume.get("experience", []) or []:
        c = (e.get("company") or "").strip()
        if not c or c in res:
            continue
        ws = _sig_words(c)
        known = any(w in ml for w in ws) if ws else c.lower() in ml
        if not known:
            res.append(c)
    return res[:limit]


def unsurfaced_supported_skills(vacancy: dict, resume: dict, master_md: str, limit: int = 8) -> list[str]:
    """Навыки вакансии, которые подтверждаются мастером, но не отражены в резюме.

    Их безопасно «дотянуть» (это не выдумка — навык реально есть в мастер-резюме)."""
    skills = [s.get("name", "").strip() for s in (vacancy.get("key_skills") or []) if s.get("name")]
    if not skills:
        return []
    rh = resume_text(resume).lower()
    ml = (master_md or "").lower()
    return [s for s in skills if not mentions(s, rh) and mentions(s, ml)][:limit]


def keyword_match(vacancy: dict, resume: dict) -> tuple[int, int, list[str]]:
    """ATS-сигнал: (покрыто, всего, не отражено) по key_skills вакансии."""
    skills = [s.get("name", "").strip() for s in (vacancy.get("key_skills") or []) if s.get("name")]
    if not skills:
        return 0, 0, []
    hay = resume_text(resume).lower()
    miss = [s for s in skills if not mentions(s, hay)]
    return len(skills) - len(miss), len(skills), miss
