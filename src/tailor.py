#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Адаптация резюме и генерация сопроводительного под конкретную вакансию.

Вход: вакансия (объект из HH), мастер-резюме (resume/master_cco.md), результат
скоринга (опц.). Выход: TailorResult — правки резюме (title / skill_set / skills)
и текст сопроводительного письма.

Качество текста здесь решает, поэтому по умолчанию используем Claude API
(официальный SDK `anthropic`, модель claude-opus-4-8). Если пакет не установлен
или нет ANTHROPIC_API_KEY — мягко падаем на детерминированный шаблон, чтобы
пайплайн всё равно работал (ядро проекта остаётся без обязательных зависимостей).

Модель можно переопределить переменной ANTHROPIC_MODEL.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MASTER_RESUME = Path(__file__).resolve().parent.parent / "resume" / "master_cco.md"
DEFAULT_MODEL = "claude-opus-4-8"


@dataclass
class TailorResult:
    resume_overrides: dict  # {"title": str, "skill_set": [str], "skills": str}
    cover_letter: str
    source: str = "template"  # "llm" | "template" — чем сгенерировано
    notes: list[str] = field(default_factory=list)


def load_master_resume() -> str:
    return MASTER_RESUME.read_text(encoding="utf-8")


def _strip_html(s: str) -> str:
    """Грубая очистка HTML-описания вакансии до читаемого текста."""
    s = re.sub(r"<(br|/p|/li|/ul|/div)\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<li[^>]*>", "• ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def vacancy_brief(vacancy: dict) -> str:
    """Короткое текстовое описание вакансии для промпта/шаблона."""
    name = vacancy.get("name", "")
    employer = (vacancy.get("employer") or {}).get("name", "")
    area = (vacancy.get("area") or {}).get("name", "")
    desc = _strip_html(vacancy.get("description", ""))
    key_skills = ", ".join(s.get("name", "") for s in vacancy.get("key_skills") or [])
    parts = [f"Вакансия: {name}", f"Компания: {employer}", f"Город: {area}"]
    if key_skills:
        parts.append(f"Ключевые навыки (из вакансии): {key_skills}")
    parts.append(f"\nОписание:\n{desc}")
    return "\n".join(parts)


# --- LLM-путь ----------------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "properties": {
        "resume_title": {"type": "string"},
        "skill_set": {"type": "array", "items": {"type": "string"}},
        "skills_text": {"type": "string"},
        "cover_letter": {"type": "string"},
    },
    "required": ["resume_title", "skill_set", "skills_text", "cover_letter"],
    "additionalProperties": False,
}

_SYSTEM = """Ты — карьерный эксперт и редактор резюме для топ-менеджеров (CMO/CCO).
Твоя задача — по мастер-резюме кандидата и конкретной вакансии подготовить:
1) resume_title — точный заголовок резюме под вакансию (название роли как у работодателя);
2) skill_set — 10–20 ключевых навыков-тегов кандидата, ПЕРЕСЕКАЮЩИХСЯ с требованиями
   вакансии (бери реальные навыки из мастер-резюме, не выдумывай);
3) skills_text — абзац «о себе/ключевая экспертиза» (4–6 предложений) под эту вакансию,
   с конкретными достижениями и цифрами из мастер-резюме;
4) cover_letter — сопроводительное письмо (6–10 предложений) от первого лица: почему
   кандидат подходит именно под ЭТУ вакансию, 2–3 релевантных достижения с цифрами,
   живой деловой тон без канцелярита и без шаблонных клише.

Жёсткие правила:
- Не выдумывай факты, компании, цифры — только то, что есть в мастер-резюме.
- Пиши по-русски, конкретно, без воды и без «командный игрок с горящими глазами».
- Сопроводительное — персонально под компанию и вакансию, а не универсальная рыба."""


def _tailor_llm(vacancy: dict, master_md: str, score_hint: str | None) -> TailorResult | None:
    """Пробует сгенерировать через Claude API. None — если SDK/ключ недоступны."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: PLC0415 — опциональная зависимость
    except ImportError:
        return None

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    user = (
        f"=== МАСТЕР-РЕЗЮМЕ КАНДИДАТА ===\n{master_md}\n\n"
        f"=== ВАКАНСИЯ ===\n{vacancy_brief(vacancy)}\n"
    )
    if score_hint:
        user += f"\n=== ПОДСКАЗКА ПО МАТЧИНГУ (наш скоринг) ===\n{score_hint}\n"

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)
    return TailorResult(
        resume_overrides={
            "title": data["resume_title"].strip(),
            "skill_set": [s.strip() for s in data["skill_set"] if s.strip()],
            "skills": data["skills_text"].strip(),
        },
        cover_letter=data["cover_letter"].strip(),
        source="llm",
        notes=[f"модель {model}"],
    )


# --- Шаблонный фолбэк (без LLM) ---------------------------------------------

def _tailor_template(vacancy: dict, matched_skills: list[str] | None) -> TailorResult:
    name = vacancy.get("name", "Руководитель")
    employer = (vacancy.get("employer") or {}).get("name", "вашей компании")
    skills = matched_skills or [
        "маркетинговая стратегия", "управление продажами", "P&L",
        "performance-маркетинг", "ROMI/CAC/LTV", "построение отделов с нуля",
        "go-to-market", "B2B Enterprise",
    ]
    skills_text = (
        "Коммерческий/маркетинговый директор с 16+ годами опыта в IT/SaaS, девелопменте "
        "и сфере услуг. Дважды выводил продукты в Топ-5 рынка, строил отделы продаж и "
        "маркетинга с нуля, управлял коммерческим блоком при масштабировании федеральных "
        "сетей. Работаю в логике P&L, ROMI, CAC/LTV. Опыт B2B Enterprise, B2G и B2C."
    )
    cover = (
        f"Здравствуйте! Заинтересовала ваша вакансия «{name}» в {employer}. "
        "За 16+ лет я выстраивал коммерческий и маркетинговый блок в IT/SaaS, девелопменте "
        "и сетевом ритейле: выводил ERP-продукт в Топ-5 рынка с планом выручки 150 млн ₽, "
        "масштабировал федеральную сеть с 3 до 14 объектов (+40% средний чек, +50% поток), "
        "увеличивал доходность стартапа в 8 раз за 3 месяца. Работаю на данных и юнит-экономике "
        "(ROMI/CAC/LTV), строю команды и системы, а не тушу пожары. "
        "Буду рад обсудить, чем могу быть полезен вашей команде."
    )
    return TailorResult(
        resume_overrides={"title": name, "skill_set": skills, "skills": skills_text},
        cover_letter=cover,
        source="template",
        notes=["LLM недоступен (нет ANTHROPIC_API_KEY или пакета anthropic) — использован шаблон"],
    )


def tailor(vacancy: dict, master_md: str | None = None,
           score_hint: str | None = None,
           matched_skills: list[str] | None = None) -> TailorResult:
    """Главная точка входа: пытается LLM, иначе — шаблон."""
    master_md = master_md or load_master_resume()
    try:
        res = _tailor_llm(vacancy, master_md, score_hint)
        if res is not None:
            return res
    except Exception as e:  # noqa: BLE001 — деградируем до шаблона, не роняя отклик
        res = _tailor_template(vacancy, matched_skills)
        res.notes.append(f"LLM-ошибка, фолбэк на шаблон: {e}")
        return res
    return _tailor_template(vacancy, matched_skills)


if __name__ == "__main__":
    # Демо на синтетической вакансии (без сети, шаблонный путь).
    demo_vacancy = {
        "name": "Коммерческий директор (CCO)",
        "employer": {"name": "IT SaaS Co"},
        "area": {"name": "Москва"},
        "description": "<p>Ищем CCO: P&amp;L, управление продажами и маркетингом, "
                       "построение отдела продаж, метрики CAC/LTV/ROMI, go-to-market.</p>",
        "key_skills": [{"name": "P&L"}, {"name": "управление продажами"}],
    }
    res = tailor(demo_vacancy)
    print(f"[источник: {res.source}]")
    print("Заголовок резюме:", res.resume_overrides["title"])
    print("Навыки:", ", ".join(res.resume_overrides["skill_set"]))
    print("\nСопроводительное:\n", res.cover_letter)
    if res.notes:
        print("\nЗаметки:", "; ".join(res.notes))
