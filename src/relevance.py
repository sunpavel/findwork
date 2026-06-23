#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скоринг релевантности вакансии профилю кандидата (CMO / CCO / Growth).

Зачем: главный запрос — матчить ТРЕБОВАНИЯ работодателя против СТЕКА/ЭКСПЕРТИЗЫ
Павла, а не просто фильтровать по индустрии. Этот модуль — переиспользуемое ядро:
на вход вакансия (заголовок + описание + зарплата), на выход скор 0..100 и
человекочитаемое объяснение (что совпало, чего не хватает, какие red flags).

К этому ядру позже подключаются:
  - источник вакансий (HH через эмуляцию приложения / парсер / Telegram-каналы);
  - LLM-доскоринг описания (тонкая семантика поверх ключевых слов);
  - отправка утреннего дайджеста в Telegram;
  - автоадаптация резюме и сопроводительного под конкретную вакансию.

Зависимостей нет — только стандартная библиотека (чтобы крутилось и на GH Actions,
и на дешёвом VPS, и на Raspberry Pi).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profile" / "profile.json"


def load_profile(path: Path = PROFILE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _norm(text: str) -> str:
    """Нижний регистр + ё→е + схлопывание пробелов. Для устойчивого матчинга."""
    text = (text or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _contains(haystack: str, needle: str) -> bool:
    """Подстрочный матч с учётом границ для коротких аббревиатур (cmo, b2b, pr...)."""
    needle = _norm(needle)
    if len(needle) <= 4 and needle.isascii():
        return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack) is not None
    return needle in haystack


@dataclass
class ScoreResult:
    score: int
    verdict: str
    best_role: str
    title_score: float
    skills_score: float
    salary_score: float
    industry_score: float
    matched_skills: list[str] = field(default_factory=list)
    missing_top_skills: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    salary_note: str = ""

    def explain(self) -> str:
        lines = [
            f"Скор: {self.score}/100 — {self.verdict}",
            f"Лучшая роль: {self.best_role}",
            f"  • заголовок: {self.title_score:.0%}  • навыки: {self.skills_score:.0%}"
            f"  • зарплата: {self.salary_score:.0%}  • отрасль: {self.industry_score:.0%}",
        ]
        if self.matched_skills:
            lines.append("  ✓ совпало: " + ", ".join(self.matched_skills[:12]))
        if self.missing_top_skills:
            lines.append("  ✗ не видно в вакансии: " + ", ".join(self.missing_top_skills[:8]))
        if self.red_flags:
            lines.append("  ⚠ red flags: " + ", ".join(self.red_flags))
        if self.salary_note:
            lines.append("  ₽ " + self.salary_note)
        return "\n".join(lines)


def _title_score(title_n: str, profile: dict) -> tuple[float, str]:
    """Максимум по целевым ролям: совпал ли титул вакансии с ключевиками роли."""
    best, best_role = 0.0, "—"
    for role in profile["target_roles"]:
        if any(_contains(title_n, kw) for kw in role["title_keywords"]):
            val = float(role["weight"])
            if val > best:
                best, best_role = val, role["name"]
    return best, best_role


def _skills_score(text_n: str, profile: dict,
                  saturation_top_n: int = 12) -> tuple[float, list[str], list[str]]:
    """Взвешенное покрытие навыков из описания. Возвращает (доля, совпавшие, топ-пропуски).

    Нормируем не на сумму ВСЕХ навыков (так любая вакансия выглядела бы нерелевантной —
    она упоминает лишь часть стека), а на «насыщение» = сумму весов топ-N навыков.
    Если вакансия покрывает столько же веса, сколько дают N самых сильных навыков
    кандидата, — это уже сильный матч (доля ≈ 1.0).
    """
    skills = profile["skills"]
    ranked = sorted(skills.items(), key=lambda kv: -kv[1])
    saturation = sum(w for _, w in ranked[:saturation_top_n]) or 1.0
    matched, matched_w = [], 0.0
    for skill, w in ranked:
        if _contains(text_n, skill):
            matched.append(skill)
            matched_w += w
    # «Пропуски» = самые весомые навыки кандидата, которых нет в вакансии
    # (полезно, чтобы понимать, чем добивать сопроводительное / на чём не акцентировать).
    missing = [s for s, _ in ranked if s not in matched][:8]
    return min(1.0, matched_w / saturation), matched, missing


def _salary_score(vac_salary: dict | None, profile: dict) -> tuple[float, str]:
    """Грубая оценка зарплатной близости. Без вилки — нейтрально (0.6)."""
    sal = profile["salary"]
    target, floor = sal["target_min"], sal["soft_floor"]
    if not vac_salary or not (vac_salary.get("from") or vac_salary.get("to")):
        return 0.6, "вилка не указана — уточнить на скрининге"
    top = vac_salary.get("to") or vac_salary.get("from")
    bottom = vac_salary.get("from") or vac_salary.get("to")
    if top >= target:
        return 1.0, f"вилка до {top:,} ≥ цели {target:,}".replace(",", " ")
    if top >= floor:
        return 0.7, f"вилка до {top:,} — ниже цели, но выше мягкого пола".replace(",", " ")
    return 0.2, f"вилка до {top:,} — заметно ниже ожиданий".replace(",", " ")


def _industry_score(text_n: str, profile: dict) -> float:
    inds = profile["industries"]
    hits = [w for name, w in inds.items() if _contains(text_n, name)]
    if not hits:
        return 0.5  # отрасль не критична (профиль кросс-индустриальный) — нейтрально
    return min(1.0, max(hits))


def _red_flags(title_n: str, text_n: str, profile: dict) -> list[str]:
    flags = []
    for w in profile["stop_words"]:
        if _contains(title_n, w):
            flags.append(f"в заголовке: {w}")
        elif _contains(text_n, w):
            flags.append(w)
    # дубли убираем, ограничиваем
    seen, out = set(), []
    for f in flags:
        if f not in seen:
            seen.add(f); out.append(f)
    return out[:6]


def _below_level(title_n: str, profile: dict) -> str | None:
    """Роль НИЖЕ целевого уровня кандидата (C-level / директор функции). Возвращает маркер или None.
    Exec-титулы (директор/CCO/CMO/коммерческий директор/вице-президент) снимают штраф, даже если
    в названии есть «отдел» (напр. «директор департамента»). Вариант B: не тратить отклики на
    под-уровневые роли (РОП, руководитель отдела/группы, тимлид, старший менеджер)."""
    lf = profile.get("level_filter") or {}
    if any(_contains(title_n, e) for e in (lf.get("exec_ok") or [])):
        return None
    for w in (lf.get("below") or []):
        if _contains(title_n, w):
            return w
    return None


def score_vacancy(title: str, description: str,
                  salary: dict | None = None,
                  profile: dict | None = None) -> ScoreResult:
    profile = profile or load_profile()
    title_n = _norm(title)
    text_n = _norm(f"{title}. {description}")

    t, best_role = _title_score(title_n, profile)
    s, matched, missing = _skills_score(text_n, profile)
    sal, sal_note = _salary_score(salary, profile)
    ind = _industry_score(text_n, profile)
    flags = _red_flags(title_n, text_n, profile)
    below = _below_level(title_n, profile)

    w = profile["scoring_weights"]
    raw = t * w["title"] + s * w["skills"] + sal * w["salary"] + ind * w["industry"]
    # штраф за red flags: каждый минус 8 баллов (в заголовке — больнее)
    penalty = sum(0.12 if f.startswith("в заголовке") else 0.06 for f in flags)
    # штраф за под-уровневую роль (вариант B): вытесняет РОП/«руководитель отдела» из дайджеста.
    if below:
        penalty += float((profile.get("level_filter") or {}).get("penalty", 0.30))
        flags = [f"ниже уровня (C-level): {below}"] + flags
    score = int(round(max(0.0, min(1.0, raw - penalty)) * 100))

    th = profile["thresholds"]
    if score >= th["auto_apply"]:
        verdict = "🔥 топ-матч — отклик в приоритете"
    elif score >= th["digest"]:
        verdict = "✅ релевантно — в дайджест"
    elif score >= th["skip_below"]:
        verdict = "🤔 пограничная — глянуть глазами"
    else:
        verdict = "✖ мимо — пропустить"

    return ScoreResult(
        score=score, verdict=verdict, best_role=best_role,
        title_score=t, skills_score=s, salary_score=sal, industry_score=ind,
        matched_skills=matched, missing_top_skills=missing,
        red_flags=flags, salary_note=sal_note,
    )


# --- демо: запусти `python3 src/relevance.py`, чтобы увидеть скоринг на примерах ---
_DEMO_VACANCIES = [
    {
        "title": "Коммерческий директор (CCO)",
        "salary": {"from": 700000, "to": 900000, "currency": "RUR"},
        "description": """Ищем коммерческого директора в IT-компанию (SaaS, B2B Enterprise).
        Полная ответственность за P&L, управление продажами и маркетингом, построение
        отдела продаж с нуля, метрики CAC/LTV/ROMI, масштабирование, go-to-market.
        Опыт запуска продукта и работы со сквозной аналитикой обязателен.""",
    },
    {
        "title": "Директор по маркетингу в девелопмент",
        "salary": {"from": 500000, "to": 650000, "currency": "RUR"},
        "description": """Девелопер жилой недвижимости ищет директора по маркетингу.
        Бренд, позиционирование, performance-маркетинг, медиапланирование, PR,
        управление командой, CRM-маркетинг, воронка продаж. Москва, гибрид.""",
    },
    {
        "title": "SMM-менеджер / таргетолог",
        "salary": {"from": 90000, "to": 130000, "currency": "RUR"},
        "description": "Нужен SMM-менеджер для ведения соцсетей. Таргет, контент, без опыта ок.",
    },
]


def _run_demo() -> None:
    profile = load_profile()
    print(f"Профиль: {profile['candidate']['name']} | "
          f"цель {profile['salary']['target_min']:,} ₽/мес\n".replace(",", " "))
    for v in _DEMO_VACANCIES:
        res = score_vacancy(v["title"], v["description"], v.get("salary"), profile)
        print(f"— {v['title']}")
        print(res.explain())
        print()


if __name__ == "__main__":
    _run_demo()
