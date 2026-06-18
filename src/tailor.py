#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Адаптация резюме и генерация сопроводительного под конкретную вакансию.

Вход: вакансия (объект из HH), мастер-резюме (resume/master_cco.md), результат
скоринга (опц.). Выход: TailorResult — правки резюме (title / skill_set / skills)
и текст сопроводительного письма.

Качество текста здесь решает, поэтому по умолчанию используем LLM. Провайдер
выбирается переменной LLM_PROVIDER:
  • openai    — ChatGPT (OPENAI_API_KEY, модель из OPENAI_MODEL, по умолчанию gpt-5);
  • anthropic — Claude  (ANTHROPIC_API_KEY, модель из ANTHROPIC_MODEL, по умолч. claude-opus-4-8).
Если LLM_PROVIDER не задан — берём openai при наличии OPENAI_API_KEY, иначе anthropic.
Если ни ключа, ни SDK нет — мягко падаем на детерминированный шаблон, чтобы
пайплайн всё равно работал (ядро проекта остаётся без обязательных зависимостей).
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MASTER_RESUME = Path(__file__).resolve().parent.parent / "resume" / "master_cco.md"
DEFAULT_MODEL = "claude-opus-4-8"          # Anthropic по умолчанию
OPENAI_DEFAULT_MODEL = "gpt-5"             # OpenAI по умолчанию


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

_SYSTEM = """Ты — senior карьерный консультант и HR-эксперт по найму топ-менеджеров
(C-level: CCO/CMO). По мастер-резюме кандидата и тексту вакансии готовишь материалы
для отклика.

ГЛАВНЫЙ ПРИНЦИП: только правда из мастер-резюме — никаких выдуманных фактов, компаний,
цифр, должностей и дат. Адаптация = переакцентировка и подбор формулировок под конкретную
вакансию, а не вымысел. Если чего-то нет в мастер-резюме — не пиши этого.

Верни JSON:
1) resume_title — заголовок резюме точно под роль из вакансии (как называет её работодатель).
2) skill_set — 12–20 навыков-тегов кандидата, максимально пересекающихся с требованиями
   вакансии; только реальные навыки из мастер-резюме; порядок — от самых релевантных вакансии.
3) skills_text — абзац «ключевая экспертиза» (4–6 предложений) под ЭТУ вакансию: с конкретикой
   и цифрами из мастер-резюме, языком и приоритетами вакансии.
4) cover_letter — сопроводительное письмо.

ТРЕБОВАНИЯ К СОПРОВОДИТЕЛЬНОМУ (от этого зависит, позовут ли на собеседование):
- Объём 180–260 слов, 3–4 коротких абзаца. Уверенный деловой тон на равных
  (топ-менеджер → нанимающему руководителю/фаундеру). Без канцелярита и клише
  («командный игрок», «стрессоустойчивый», «нацелен на результат», «горящие глаза»).
- Абзац 1 — цепляющее начало под конкретную компанию/продукт и задачу из вакансии,
  а не «меня заинтересовала ваша вакансия». Если название компании известно — обратись
  к ней по имени; если нет — открывай через роль и задачу, без пустого «в .».
- Абзацы 2–3 — 2–3 достижения ИМЕННО под требования этой вакансии, с цифрами и контекстом
  из мастер-резюме; явно свяжи их с тем, что нужно работодателю.
- Финал — что кандидат сделает для их бизнеса (фокус на первые 60–90 дней для senior-роли)
  и короткий призыв обсудить.
- Пиши по-русски, конкретно, по делу. Естественно зеркаль ключевые слова вакансии
  (важно для скрининга), но без переспама."""


def _build_user(vacancy: dict, master_md: str, score_hint: str | None) -> str:
    user = (
        f"=== МАСТЕР-РЕЗЮМЕ КАНДИДАТА ===\n{master_md}\n\n"
        f"=== ВАКАНСИЯ ===\n{vacancy_brief(vacancy)}\n"
    )
    if score_hint:
        user += f"\n=== ПОДСКАЗКА ПО МАТЧИНГУ (наш скоринг) ===\n{score_hint}\n"
    return user


def _result_from_json(data: dict, note: str) -> TailorResult:
    return TailorResult(
        resume_overrides={
            "title": data["resume_title"].strip(),
            "skill_set": [s.strip() for s in data["skill_set"] if s.strip()],
            "skills": data["skills_text"].strip(),
        },
        cover_letter=data["cover_letter"].strip(),
        source="llm",
        notes=[note],
    )


def _provider() -> str:
    """Какой LLM использовать: openai | anthropic | none."""
    p = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if p in ("openai", "anthropic"):
        return p
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "none"


def _tailor_openai(vacancy: dict, master_md: str, score_hint: str | None) -> TailorResult | None:
    """Генерация через OpenAI Chat Completions (чистый urllib, без пакета openai)."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    model = os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_user(vacancy, master_md, score_hint)},
        ],
        # max_completion_tokens (а не max_tokens) — иначе reasoning-модели (gpt-5) ругаются.
        "max_completion_tokens": int(os.environ.get("OPENAI_MAX_TOKENS", "6000")),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "tailor", "strict": True, "schema": _SCHEMA},
        },
    }
    # У gpt-5/o-моделей глубина раздумий сильно влияет на скорость: minimal ≈ 9 сек,
    # default ≈ 40+ сек. Для интерактивного бота по умолчанию minimal. Параметр шлём
    # ТОЛЬКО reasoning-моделям (gpt-4.1 его не принимает).
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "minimal")
    if effort and model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["reasoning_effort"] = effort
    req = urllib.request.Request(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    data = json.loads(d["choices"][0]["message"]["content"])
    return _result_from_json(data, f"OpenAI {model}")


def _tailor_anthropic(vacancy: dict, master_md: str, score_hint: str | None) -> TailorResult | None:
    """Генерация через Claude API (SDK anthropic). None — если SDK/ключ недоступны."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: PLC0415 — опциональная зависимость
    except ImportError:
        return None

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_user(vacancy, master_md, score_hint)}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _result_from_json(json.loads(text), f"Claude {model}")


def _tailor_llm(vacancy: dict, master_md: str, score_hint: str | None) -> TailorResult | None:
    """Выбирает провайдера и генерирует. None — если LLM недоступен."""
    provider = _provider()
    if provider == "openai":
        return _tailor_openai(vacancy, master_md, score_hint)
    if provider == "anthropic":
        return _tailor_anthropic(vacancy, master_md, score_hint)
    return None


# --- Шаблонный фолбэк (без LLM) ---------------------------------------------

def _tailor_template(vacancy: dict, matched_skills: list[str] | None) -> TailorResult:
    name = vacancy.get("name", "Руководитель")
    employer = (vacancy.get("employer") or {}).get("name") or "вашей компании"
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
        notes=["LLM недоступен (нет ключа OPENAI/ANTHROPIC или пакета) — использован шаблон"],
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
