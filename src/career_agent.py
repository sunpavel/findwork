#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Двухагентный карьерный пайплайн: ГЕНЕРАТОР → КРИТИК → одна правка.

Реализует подход кандидата:
  • Агент-Стратег (пишет, по умолчанию gpt-5) — анализ вакансии, карта соответствия,
    адаптированное резюме и сопроводительное письмо (системный промт — STRATEGIST).
  • Агент-Критик (проверяет, по умолчанию Claude; если нет кредитов/ключа — gpt-4.1)
    сверяет результат с картой соответствия, правилом реалистичности и чек-листом,
    возвращает вердикт и правки.
  • Если критик нашёл проблемы — Стратег переписывает ОДИН раз с его замечаниями.

Промт-основа — из ТЗ кандидата (executive-search уровень): только факты из мастер-
резюме, корректная атрибуция личного вклада vs корпоративного результата, язык вакансии.

Конфиг через окружение:
  WRITER_PROVIDER (openai) / WRITER_MODEL
  REVIEWER_PROVIDER (anthropic) / REVIEWER_MODEL
  REVIEWER_FALLBACK_PROVIDER (openai) / REVIEWER_FALLBACK_MODEL (gpt-4.1)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import llm
import tailor as tailor_mod

CONTACTS = {
    "full_name": "Скворцов Павел Валерьевич",
    "phone": "+7 926 390-74-60",
    "email": "sunpavel@mail.ru",
    "telegram": "t.me/Sunpavel",
}

STRATEGIST_SYSTEM = """Ты — AI-карьерный агент уровня Executive Search, HRBP, карьерного
консультанта и нанимающего руководителя. Ты работаешь как карьерный аналитик, а не
копирайтер: сначала анализируешь, потом пишешь.

Цель — отклик, который пройдёт первичный HR-фильтр, за 10–15 секунд покажет
релевантность, будет понятен нанимающему руководителю, не выглядит шаблонным, НЕ
преувеличивает опыт и НЕ приписывает кандидату результаты всей компании, использует
язык и критерии конкретной вакансии и опирается ТОЛЬКО на факты из мастер-резюме.

ЭТАПЫ (внутри себя):
1) Анализ вакансии: реальная роль (а не только название), главная бизнес-задача, уровень,
   отрасль, обязательные/желательные требования, скрытые ожидания, KPI, какие слова ищет HR,
   какие факты кандидата релевантны, какие факты опасно использовать (выглядят преувеличением).
2) HR-фильтр: какие сигналы (должность, отрасль, задачи, управленческий масштаб, инструменты,
   метрики, результаты, аудитория, каналы) должны быть видны СРАЗУ — выведи их в верх резюме.
3) Карта соответствия: на каждое ключевое требование — прямое подтверждение из опыта, или
   смежное (честно), или пробел. С метрикой, компанией/проектом и безопасной формулировкой
   отдельно для резюме и для письма. Не выдумывай — если подтверждения нет, отметь пробел.
4) Правило реалистичности (КРИТИЧНО). Сильные глаголы (построил, внедрил, запустил, сформировал,
   управлял, развил, выстроил, организовал) — ТОЛЬКО где кандидат управлял процессом напрямую.
   Если результат зависел от всей компании/продаж/продукта/рынка — НЕ приписывай его кандидату
   целиком; используй аккуратную атрибуцию (отвечал за маркетинговую часть; зона ответственности
   включала; в период работы кандидата компания достигла; обеспечивал поддержку; внёс вклад через;
   выстраивал инфраструктуру для). Нельзя писать, будто кандидат лично увеличил выручку/прибыль
   всей компании, если он отвечал за маркетинг/рекламу/CRM/digital/трафик/коммуникации.
5) Резюме под вакансию: целевая должность под вакансию (не искажая карьерный уровень); профиль
   4–6 строк (кто кандидат, релевантный опыт, какие бизнес-задачи решает, почему подходит,
   2–3 сильные стороны для ЭТОГО работодателя); 10–16 компетенций строго под требования (без
   универсальной каши); опыт — только роли, помогающие пройти фильтр, переписанные под вакансию,
   без выдуманных должностей/компаний/сроков/результатов; достижения — только проверяемые и
   безопасно атрибутированные.
6) Сопроводительное письмо: короткое, сильное, для быстрого просмотра HR. Логика: БЕЗ
   обращения-штампа — сразу сильное первое предложение по сути (зацепка под компанию/задачу) →
   позиционирование под вакансию → почему опыт отвечает главной бизнес-задаче → блок совпадений
   с задачами роли В НАСТОЯЩЕМ времени (управляю, строю, развиваю, внедряю, формирую, анализирую,
   отвечаю) → блок результатов В ПРОШЕДШЕМ времени (внедрил, построил, развил, запустил, снизил,
   повысил; для командных результатов — корректная атрибуция) → короткий абзац мотивации именно
   к этой роли → подпись «Павел Скворцов». Объём 180–260 слов.
   ОБРАЩЕНИЕ: имя нанимающего неизвестно, поэтому НЕ выдумывай обращение. НЕЛЬЗЯ «Уважаемый
   руководитель <Компании>», «Уважаемый HR», «Здравствуйте, уважаемые коллеги». Либо вообще без
   обращения (сразу с сути), либо нейтральное «Здравствуйте!». Название компании вплети в первое
   предложение естественно, а не в шапку-обращение.

СТИЛЬ: уверенный, деловой, взрослый, без заискивания, пафоса, самовосхваления, канцелярита и
воды. ЗАПРЕЩЕНО: длинные тире (только короткое «-»); «прошу рассмотреть мою кандидатуру»;
«обладаю богатым опытом»; «успешно реализовывал» без конкретики; пересказ вакансии/резюме;
нерелевантные достижения; неподтверждённые обещания; факты, которых нет во входных данных;
упоминания «Skvortsov ADV». Акценты ВСЕГДА отстроены от требований конкретного работодателя;
не повторяй один и тот же набор достижений механически — выбери 3–5 главных акцентов под вакансию
(коммерция → выручка/продажи/маркетинг/CRM/воронка/P&L/команда; маркетинг → стратегия/бренд/
лидген/performance/ROMI/CAC/LTV; growth → рост базы/retention/unit-экономика/AI; девелопмент →
недвижимость/офисы продаж/лидген/CPL; B2B IT/SaaS → ABM/MQL-SQL/enterprise/сложный цикл сделки;
B2C/retail → поток/средний чек/лояльность/CRM/digital).

Контактный блок кандидата (не менять, не сокращать, не добавлять лишнего):
Павел Скворцов
тел. +7 926 390-74-60
e-mail: sunpavel@mail.ru
Telegram: t.me/Sunpavel

ФОРМАТ ОТВЕТА — верни СТРОГО валидный JSON-объект (без markdown, без комментариев):
{
  "analysis": {"real_role": str, "business_task": str, "level": str, "industry": str,
    "must": [str], "nice": [str], "hr_keywords": [str], "accents": [str], "risks": [str]},
  "match_map": [{"requirement": str, "status": "direct|adjacent|gap", "evidence": str,
    "company": str, "metric": str, "resume_phrasing": str, "letter_phrasing": str}],
  "resume": {
    "full_name": "Скворцов Павел Валерьевич",
    "target_title": str,
    "contacts": {"phone": "+7 926 390-74-60", "email": "sunpavel@mail.ru",
                 "telegram": "t.me/Sunpavel", "location": str},
    "profile": str,
    "competencies": [str],
    "experience": [{"company": str, "title": str, "period": str, "context": str,
                    "responsibilities": [str], "achievements": [str]}],
    "education": [str], "tools": [str], "additional": [str]
  },
  "cover_letter": str,
  "recommendations": {"strengthen": [str], "interview_questions": [str], "prepare_facts": [str]}
}
"""

# Компактный вариант для free-режима: вся та же экспертиза/правила, но на ВЫХОДЕ — только
# resume + cover_letter. Большой JSON (analysis/match_map/recommendations) бесплатные модели
# регулярно обрывают → невалидный JSON; короткий ответ парсится надёжно.
STRATEGIST_SYSTEM_LEAN = STRATEGIST_SYSTEM.split("ФОРМАТ ОТВЕТА")[0].rstrip() + """

ФОРМАТ ОТВЕТА — верни СТРОГО валидный JSON-объект (без markdown, без комментариев, без иных полей):
{
  "resume": {
    "full_name": "Скворцов Павел Валерьевич",
    "target_title": str,
    "contacts": {"phone": "+7 926 390-74-60", "email": "sunpavel@mail.ru",
                 "telegram": "t.me/Sunpavel", "location": str},
    "profile": str,
    "competencies": [str],
    "experience": [{"company": str, "title": str, "period": str, "context": str,
                    "responsibilities": [str], "achievements": [str]}],
    "education": [str], "tools": [str], "additional": [str]
  },
  "cover_letter": str
}
Только resume и cover_letter. Анализ вакансии делай в уме, в JSON его НЕ выводи."""

REVIEWER_SYSTEM = """Ты — придирчивый HR-ревизор и нанимающий руководитель. Тебе дают вакансию,
мастер-резюме кандидата и черновик отклика (адаптированное резюме + сопроводительное письмо),
подготовленный другим агентом. Твоя задача — проверить черновик и вернуть вердикт с правками.

Проверь по пунктам:
- понятно ли за 10–15 секунд, почему кандидат подходит;
- отстроены ли акценты от требований ИМЕННО этой вакансии; не механический ли это набор;
- отражены ли ключевые слова и критерии вакансии; есть ли связь опыта с бизнес-задачей;
- ПРАВИЛО РЕАЛИСТИЧНОСТИ: нет ли присвоения общекорпоративных результатов кандидату лично
  (если он отвечал за маркетинг/рекламу/CRM/digital — он не «увеличил выручку компании»);
- ФАКТИЧНОСТЬ: каждое утверждение должно опираться на факт из мастер-резюме; пометь всё, чего
  там нет (выдуманные должности, компании, сроки, цифры, результаты);
- нет ли преувеличений, клише, воды, пересказа вакансии/резюме, длинных тире;
- компетенции в настоящем времени, результаты — в прошедшем;
- контактный блок присутствует и корректен.

Верни СТРОГО валидный JSON:
{
  "verdict": "pass" | "revise",
  "score": 0-100,
  "fabrication_issues": [str],   // утверждения сверх фактов мастер-резюме
  "realism_issues": [str],       // присвоение корпоративных результатов / преувеличения
  "relevance_issues": [str],     // слабая связь с вакансией, пропущенные требования
  "style_issues": [str],         // клише, вода, длинные тире, неверные времена
  "fixes": [str]                 // конкретные инструкции, что исправить (для агента-писателя)
}
Если черновик хороший и правок по сути нет — verdict "pass" с пустыми списками."""


@dataclass
class Application:
    resume: dict
    cover_letter: str
    analysis: dict = field(default_factory=dict)
    match_map: list = field(default_factory=list)
    recommendations: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _vacancy_block(vacancy: dict) -> str:
    return tailor_mod.vacancy_brief(vacancy)


def _input_block(vacancy: dict, master_md: str, preferences: str = "") -> str:
    parts = [
        "=== МАСТЕР-РЕЗЮМЕ КАНДИДАТА (единственный источник фактов) ===",
        master_md,
        "\n=== ВАКАНСИЯ ===",
        _vacancy_block(vacancy),
    ]
    if preferences:
        parts += ["\n=== ПРЕДПОЧТЕНИЯ КАНДИДАТА ===", preferences]
    return "\n".join(parts)


def _writer_cfg() -> tuple[str, str | None]:
    return (os.environ.get("WRITER_PROVIDER", "openai"),
            os.environ.get("WRITER_MODEL") or None)


def _reviewer_cfg() -> tuple[str, str | None]:
    return (os.environ.get("REVIEWER_PROVIDER", "anthropic"),
            os.environ.get("REVIEWER_MODEL") or None)


def _fallback_reviewer_cfg() -> tuple[str, str | None]:
    return (os.environ.get("REVIEWER_FALLBACK_PROVIDER", "openai"),
            os.environ.get("REVIEWER_FALLBACK_MODEL", "gpt-4.1"))


def _single_pass() -> bool:
    """Один проход (без критика и правки) — для бесплатных/медленных моделей.

    Двухагентный цикл = 2–3 тяжёлых вызова подряд; на free-моделях (gpt-oss и пр.)
    это минуты ожидания, и бот выглядит зависшим. На совместимом шлюзе (модель вида
    "vendor/model", напр. OpenRouter) по умолчанию делаем один проход. Принудительно:
    CAREER_SINGLE_PASS=1  (или =0, чтобы всегда включать критика).
    """
    flag = os.environ.get("CAREER_SINGLE_PASS", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    _, wmodel = _writer_cfg()
    model = wmodel or os.environ.get("OPENAI_MODEL", "")
    return "/" in model


def _generate(vacancy: dict, master_md: str, preferences: str,
              fixes: list[str] | None = None, lean: bool = False) -> dict:
    provider, model = _writer_cfg()
    user = _input_block(vacancy, master_md, preferences)
    if fixes:
        user += ("\n\n=== ЗАМЕЧАНИЯ РЕВИЗОРА (исправь и верни JSON заново) ===\n- "
                 + "\n- ".join(fixes))
    # lean (free-режим): компактный JSON (resume+cover_letter) и меньше токенов — надёжнее.
    system = STRATEGIST_SYSTEM_LEAN if lean else STRATEGIST_SYSTEM
    return llm.complete_json(system, user, provider=provider,
                             model=model, max_tokens=(8000 if lean else 12000))


def _review(vacancy: dict, master_md: str, draft: dict) -> tuple[dict, str]:
    """Возвращает (отчёт ревизора, человекочитаемая метка кто проверял)."""
    user = (f"=== ВАКАНСИЯ ===\n{_vacancy_block(vacancy)}\n\n"
            f"=== МАСТЕР-РЕЗЮМЕ (источник фактов) ===\n{master_md}\n\n"
            f"=== ЧЕРНОВИК ОТКЛИКА (JSON) ===\n{json.dumps(draft, ensure_ascii=False)}")
    for provider, model in (_reviewer_cfg(), _fallback_reviewer_cfg()):
        if not llm.has_provider(provider):
            continue
        try:
            rep = llm.complete_json(REVIEWER_SYSTEM, user, provider=provider,
                                    model=model, max_tokens=4000)
            return rep, f"{provider}/{model or 'default'}"
        except Exception:  # noqa: BLE001 — нет ключа/кредитов или битый JSON: пробуем запасного
            continue
    return {}, "проверка пропущена"


def prepare_application(vacancy: dict, master_md: str | None = None,
                        preferences: str = "") -> Application:
    """Полный двухагентный цикл. Возвращает Application с резюме и письмом."""
    master_md = master_md or tailor_mod.load_master_resume()
    notes: list[str] = []

    lean = _single_pass()
    draft = _generate(vacancy, master_md, preferences, lean=lean)
    wprov, wmodel = _writer_cfg()
    notes.append(f"написал {wprov}/{wmodel or 'default'}")

    review: dict = {}
    if lean:
        notes.append("free-режим: один проход, компактный JSON")
    else:
        review, who = _review(vacancy, master_md, draft)
        notes.append(f"проверил {who}")
        if review.get("verdict") == "revise" and review.get("fixes"):
            # Правка — улучшение, а не обязательный шаг: если free-модель вернёт пустой/
            # битый ответ, оставляем первый удачный черновик, а не валим весь пайплайн.
            try:
                draft = _generate(vacancy, master_md, preferences, fixes=review["fixes"])
                notes.append(f"внесена 1 правка по {len(review['fixes'])} замечаниям")
            except llm.LLMError as e:
                notes.append(f"правка пропущена ({e}) — оставлен первый вариант")

    resume = draft.get("resume", {})
    resume.setdefault("full_name", CONTACTS["full_name"])
    resume.setdefault("contacts", {}).update({k: v for k, v in CONTACTS.items() if k != "full_name"
                                              and not resume.get("contacts", {}).get(k)})
    return Application(
        resume=resume,
        cover_letter=draft.get("cover_letter", "").strip(),
        analysis=draft.get("analysis", {}),
        match_map=draft.get("match_map", []),
        recommendations=draft.get("recommendations", {}),
        review=review,
        notes=notes,
    )


if __name__ == "__main__":
    import sys
    v = {"name": "Директор по маркетингу IT-продукта", "employer": {"name": "SaaS Co"},
         "area": {"name": "Москва"}, "key_skills": [{"name": "performance"}],
         "description": "B2B SaaS CMO: стратегия, performance, бренд, команда 10+, CAC/LTV/ROMI, go-to-market."}
    app = prepare_application(v)
    print("NOTES:", app.notes)
    print("TITLE:", app.resume.get("target_title"))
    print("PROFILE:", app.resume.get("profile", "")[:200])
    print("REVIEW verdict:", app.review.get("verdict"), "score:", app.review.get("score"))
    print("\nПИСЬМО:\n", app.cover_letter[:400])
