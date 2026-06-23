#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Умная релевантность вакансии под РЕАЛЬНЫЙ опыт кандидата (LLM-судья).

Keyword-скоринг (relevance.py) не понимает уровень, масштаб и смысл: «руководитель
группы маркетинга» и «директор по маркетингу» для него почти одно. Этот модуль
добавляет слой, заземлённый на МАСТЕР-РЕЗЮМЕ: LLM оценивает, насколько вакансия —
шаг в уровень и по экспертизе Павла, и честно показывает, чем закрывает требования
и где пробелы/риски.

Двухступенчато (чтобы не жечь токены на мусоре):
  1) дешёвый keyword-пре-фильтр (relevance.score_vacancy) — отсекает явно нерелевантное;
  2) LLM-судья на топ-K выживших — ранжирует по реальному попаданию в профиль.

LLM ходит через общий llm.py (по умолчанию — премиум n8n/ChatGPT, провайдер сам).
Если LLM недоступен — вызывающий код откатывается на keyword-скоринг.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import llm
import tailor as tailor_mod
from relevance import load_profile, score_vacancy

FIT_SYSTEM = """Ты — придирчивый карьерный эксперт уровня Executive Search. Оцениваешь,
насколько вакансия подходит КОНКРЕТНОМУ кандидату по его реальному опыту и УРОВНЮ, а не
по совпадению слов. Тебе дают мастер-резюме кандидата (единственный источник правды о его
опыте) и вакансию.

Думай по сути, не по ключевым словам:
1. Функция: совпадает ли направление (коммерция / маркетинг / рост) с экспертизой кандидата.
2. УРОВЕНЬ и масштаб. Целевой уровень кандидата — ДИРЕКТОР ФУНКЦИИ / C-level: коммерческий
   директор (CCO), директор по маркетингу (CMO), директор по развитию/продажам, глава
   направления, вице-президент. Такие роли считай «в уровень» (это его целевая полка, НЕ
   понижение). «Ниже» (МИНУС, низкий балл) — руководитель/начальник ОТДЕЛА (РОП, руководитель
   отдела продаж/маркетинга), руководитель группы, тимлид, старший/рядовой
   менеджер, специалист, координатор. «Выше» (риск) — первое лицо крупной корпорации (CEO
   большой компании), где его опыта по масштабу может не хватать.
3. Отрасль: близка ли она его опыту (профиль кросс-индустриальный — отрасль не вето).
4. Требования: какие ключевые требования вакансии кандидат реально закрывает ОПЫТОМ (с
   конкретикой из резюме), а какие — пробел.
5. Красные флаги: продажи «в полях», пустой титул, агентство/массовый найм, неполная
   занятость, переезд (кандидат не готов), узкая нерелевантная специфика.

Верни СТРОГО валидный JSON (без markdown):
{
  "fit_score": 0-100,           // 80+ сильное попадание в ЕГО профиль; 55-79 релевантно; <55 слабо
  "level_match": "ниже" | "в уровень" | "выше",
  "why": "1-2 предложения: почему релевантно ИМЕННО его опыту, с конкретикой",
  "evidence": ["2-4 факта из резюме, закрывающие требования вакансии"],
  "gaps": ["чего не хватает / на что обратить внимание — честно"],
  "risks": ["красные флаги: уровень/переезд/агентство/специфика — может быть пусто"]
}
Балл отражает пользу ДЛЯ КАНДИДАТА: высокий — только если это шаг в его уровень и по его
экспертизе. Не завышай за простое совпадение слов; понижение по уровню — низкий балл."""


@dataclass
class FitResult:
    score: int
    why: str = ""
    level_match: str = ""
    evidence: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source: str = "llm"


def _area_name(vacancy: dict) -> str:
    area = vacancy.get("area")
    if isinstance(area, dict):
        return area.get("name", "")
    return area or ""


def _key_skills(vacancy: dict) -> str:
    ks = vacancy.get("key_skills") or []
    if ks and isinstance(ks[0], dict):
        return ", ".join(s.get("name", "") for s in ks)
    return ", ".join(ks) if ks else ""


def _vacancy_text(vacancy: dict) -> str:
    """Бриф вакансии для судьи — работает и с нормализованным видом (sources.py),
    и с сырым HH-объектом (name/employer/...)."""
    title = vacancy.get("title") or vacancy.get("name") or ""
    company = vacancy.get("company") or (vacancy.get("employer") or {}).get("name", "")
    desc = tailor_mod._strip_html(vacancy.get("description", ""))
    parts = [f"Название: {title}", f"Компания: {company}", f"Город: {_area_name(vacancy)}"]
    ks = _key_skills(vacancy)
    if ks:
        parts.append(f"Ключевые навыки: {ks}")
    if vacancy.get("salary"):
        parts.append(f"Зарплата (как в вакансии): {vacancy['salary']}")
    parts.append("Описание:\n" + desc[:3000])
    return "\n".join(parts)


def score_fit(vacancy: dict, master_md: str | None = None,
              provider: str | None = None) -> FitResult:
    """LLM-оценка попадания вакансии под реальный опыт/уровень кандидата."""
    master_md = master_md or tailor_mod.load_master_resume()
    user = (f"=== МАСТЕР-РЕЗЮМЕ КАНДИДАТА (источник правды о его опыте) ===\n{master_md[:4000]}\n\n"
            f"=== ВАКАНСИЯ ===\n{_vacancy_text(vacancy)}")
    provider = provider or llm.default_provider()
    data = llm.complete_json(FIT_SYSTEM, user, provider=provider, max_tokens=900)
    return FitResult(
        score=int(data.get("fit_score", 0) or 0),
        why=(data.get("why") or "").strip(),
        level_match=(data.get("level_match") or "").strip(),
        evidence=[str(x) for x in (data.get("evidence") or [])][:4],
        gaps=[str(x) for x in (data.get("gaps") or [])][:4],
        risks=[str(x) for x in (data.get("risks") or [])][:4],
    )


def rank_smart(vacancies: list[dict], profile: dict | None = None,
               master_md: str | None = None, *, prefilter_min: int = 35,
               top_k: int = 20, fit_min: int | None = None) -> list[tuple[dict, FitResult]]:
    """Двухступенчатое ранжирование: keyword-пре-фильтр → LLM-судья → сортировка по fit.

    prefilter_min — мин. keyword-скор, чтобы вакансия дошла до LLM (экономим токены);
    top_k         — сколько лучших по keyword отдаём судье;
    fit_min       — порог LLM-оценки для попадания в выдачу (по умолчанию thresholds.digest)."""
    profile = profile or load_profile()
    master_md = master_md or tailor_mod.load_master_resume()
    if fit_min is None:
        fit_min = profile["thresholds"]["digest"]

    pre: list[tuple[dict, int]] = []
    for v in vacancies:
        r = score_vacancy(v.get("title") or v.get("name", ""),
                          v.get("description", ""), v.get("salary"), profile)
        if r.score >= prefilter_min:
            pre.append((v, r.score))
    pre.sort(key=lambda pr: pr[1], reverse=True)

    out: list[tuple[dict, FitResult]] = []
    for v, kw in pre[:top_k]:
        try:
            fr = score_fit(v, master_md)
        except Exception:  # noqa: BLE001 — судья споткнулся: оставляем keyword-оценку
            fr = FitResult(score=kw, why="(keyword-фолбэк: LLM недоступен)", source="keyword")
        if fr.score >= fit_min:
            out.append((v, fr))
    out.sort(key=lambda pr: pr[1].score, reverse=True)
    return out


if __name__ == "__main__":
    # Демо: оцениваем три вакансии разного уровня против мастер-резюме.
    demos = [
        {"title": "Директор по развитию бизнеса (новые направления)", "company": "Лоджик Старс",
         "salary": {"from": 500000, "to": 800000},
         "description": "Создание новых направлений, P&L, вывод продуктов на рынок, B2B, MVP, рост выручки."},
        {"title": "Руководитель группы маркетинга", "company": "Ритейл Сеть",
         "salary": {"from": 180000, "to": 220000},
         "description": "Управление группой из 3 маркетологов, контент, SMM, отчётность руководителю."},
        {"title": "SMM-менеджер", "company": "Агентство",
         "salary": {"from": 90000, "to": 120000},
         "description": "Ведение соцсетей, таргет, контент-план."},
    ]
    for v in demos:
        fr = score_fit(v)
        print(f"{fr.score}/100 [{fr.level_match}] — {v['title']}")
        print("  why:", fr.why)
        if fr.gaps:
            print("  gaps:", "; ".join(fr.gaps))
        if fr.risks:
            print("  risks:", "; ".join(fr.risks))
        print()
