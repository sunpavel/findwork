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
import time
import urllib.error
import urllib.request

import llm
from dataclasses import dataclass, field
from pathlib import Path

MASTER_RESUME = Path(__file__).resolve().parent.parent / "resume" / "master_cco.md"
DEFAULT_MODEL = "claude-opus-4-8"          # Anthropic по умолчанию
OPENAI_DEFAULT_MODEL = "gpt-5"             # OpenAI по умолчанию

# --- Единый стандарт оформления сопроводительного (общий для tailor и career_agent) ---
# Контактный блок подписи: фиксированный, ровно как в письмах кандидата.
COVER_LETTER_SIGNATURE = (
    "С уважением,\n"
    "Павел Скворцов\n"
    "+7 926 390-74-60\n"
    "sunpavel@mail.ru\n"
    "t.me/Sunpavel"
)

# Спецификация структуры и оформления письма + эталон стиля кандидата (his own letter).
# Модель регулярно льёт письмо одним полотном — здесь даём ей буквальный скелет с абзацами,
# блоком «задачи вакансии → чем закрываю» и построчной подписью.
COVER_LETTER_SPEC = """СТРУКТУРА И ОФОРМЛЕНИЕ ПИСЬМА — соблюдай буквально (читаемость критична):
Письмо — это НЕ сплошное полотно, а 5-6 коротких АБЗАЦЕВ, разделённых ПУСТОЙ СТРОКОЙ.
Внутри абзаца переносов строк нет. Скелет:

Здравствуйте!

<Зацепка: 1-2 предложения — почему интересна именно эта вакансия/компания, через твой
релевантный домен. Название компании вплети в текст естественно, без шапки-обращения.>

<Позиционирование под роль + 1-2 главных достижения под её ключевую задачу — с названиями
компаний и ЦИФРАМИ из мастер-резюме.>

Ключевые задачи роли, которые закрою опытом:
— <реальная задача/требование ИЗ ТЕКСТА вакансии 1>: <чем закрываю, метрика/компания из мастера>;
— <задача/требование 2>: <чем закрываю, метрика из мастера>;
— <задача/требование 3>: <чем закрываю, метрика из мастера>.

<Короткий человеческий абзац: почему интересна именно эта роль/команда. Без пафоса.>

Буду рад обсудить, как мой опыт может быть полезен <компании/команде>.

С уважением,
Павел Скворцов
+7 926 390-74-60
sunpavel@mail.ru
t.me/Sunpavel

ПРАВИЛА ОФОРМЛЕНИЯ:
- Список «Ключевые задачи…»: 3-5 пунктов, маркер «— » (тире и пробел), каждый с новой строки,
  пункты идут подряд без пустых строк между ними. Пункты — это РЕАЛЬНЫЕ задачи/требования из
  текста ЭТОЙ вакансии (зеркаль её формулировки), под каждым — чем закрываешь, с цифрой из мастера.
- Между смысловыми абзацами — ровно одна пустая строка.
- Подпись — отдельным блоком в конце, каждый контакт на своей строке, ровно эти контакты (не менять).
- Длинных тире «—» в тексте абзацев НЕ использовать (только короткое «-»); «— » допустимо ТОЛЬКО
  как маркер пунктов списка.

ЭТАЛОН СТИЛЯ, ТОНА И ПЛОТНОСТИ ЦИФР. ВАЖНО: ниже — ВЫМЫШЛЕННЫЙ кандидат из ДРУГОЙ отрасли. Это
образец только СТРУКТУРЫ, ТОНА и ПЛОТНОСТИ ЦИФР. Компании, отрасль, цифры и формулировки НЕ
копируй — все факты бери СТРОГО из мастер-резюме под конкретную вакансию (иначе это выдумка).
ОСОБЕННО НЕ КОПИРУЙ: (1) зацепку — в образце она обобщённая, в реальном письме первое предложение
про специфику ИМЕННО твоей вакансии; (2) пункты «Ключевые задачи роли» — в образце они общие, для
демонстрации формата; в реальном письме это ДОСЛОВНЫЕ требования из текста конкретной вакансии,
под каждым — чем закрываешь с цифрой из мастера. Подпись — каноническая (контакты кандидата), её
оставляй как есть:
<<<
Здравствуйте!

Меня заинтересовала ваша вакансия, потому что маркетинг здесь - не «отдел рекламы», а драйвер
роста бизнеса, влияющий на продажи, продукт и экономику компании.

В сети «ФрешМаркет» (e-grocery) отвечал за маркетинг и коммерцию направления с оборотом 2,4 млрд ₽:
вывел выручку онлайн-канала с 320 до 540 млн ₽ за год, поднял средний чек на 18%, снизил CAC на
25% при росте базы активных клиентов в 2 раза.

Ключевые задачи роли, которые закрою опытом:
— построение performance и сквозной аналитики с привязкой к продажам и ROI;
— управление digital-каналами и лидогенерацией;
— выстраивание процессов и KPI внутри команды;
— связка маркетинга, продукта и продаж в единую систему.

Нахожусь в Москве, готов обсуждать гибридный формат. Буду рад обсудить, как мой опыт может быть
полезен вашей команде.

С уважением,
Павел Скворцов
+7 926 390-74-60
sunpavel@mail.ru
t.me/Sunpavel
>>>"""

_SIG_MARKERS = ("С уважением", "С Уважением", "Павел Скворцов", "Скворцов Павел",
                "+7 926 390", "+7926390")


def format_cover_letter(text: str) -> str:
    """Гарантирует читаемое оформление письма: абзацы через пустую строку и единый
    корректный блок подписи (каждый контакт на своей строке).

    Промпт уже просит такую структуру; это детерминированная страховка на случай, если
    модель склеила подпись в строку или насыпала лишних пустых строк. Тело письма (его
    разбивку на абзацы по смыслу) задаёт промпт — здесь его не переписываем."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return t
    # Отрезаем подпись модели (по самому раннему её маркеру) и ставим свою, канонічную.
    cut = len(t)
    for m in _SIG_MARKERS:
        i = t.find(m)
        if i != -1:
            cut = min(cut, i)
    body = t[:cut].rstrip()
    body = re.sub(r"[ \t]+\n", "\n", body)        # хвостовые пробелы в строках
    body = re.sub(r"\n[ \t]+", "\n", body)        # ведущие пробелы в строках
    body = re.sub(r"\n{3,}", "\n\n", body)        # 3+ переноса → абзацный интервал
    body = re.sub(r"^(Здравствуйте[!.]?)[ \t]*\n(?!\n)", r"\1\n\n", body)  # пустая строка после приветствия
    return (body + "\n\n" + COVER_LETTER_SIGNATURE).strip()


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
- Уверенный деловой тон на равных (топ-менеджер → нанимающему руководителю/фаундеру),
  по-русски, конкретно, без канцелярита и клише («командный игрок», «стрессоустойчивый»,
  «нацелен на результат», «горящие глаза»).
- 2-3 достижения ИМЕННО под требования этой вакансии, с цифрами и контекстом из мастер-резюме,
  явно связанные с тем, что нужно работодателю; естественно зеркаль ключевые слова вакансии.
- Без обращений-штампов («Уважаемый руководитель <Компании>», «Уважаемый HR») — имя адресата
  неизвестно; либо нейтральное «Здравствуйте!», либо сразу с сути.
- Объём 180-260 слов. Структуру и ОФОРМЛЕНИЕ бери из блока ниже и соблюдай буквально.

""" + COVER_LETTER_SPEC


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
        cover_letter=format_cover_letter(data["cover_letter"]),
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


def _loads_lenient(text: str) -> dict:
    """Разбирает JSON из ответа модели, терпимо к ```json-обёрткам и преамбулам.

    Бесплатные OpenAI-совместимые модели (OpenRouter и т.п.) часто не дают чистый
    JSON: оборачивают в ```json или добавляют пояснения. Реальный OpenAI со strict
    json_schema даёт чистый JSON — для него путь тоже отрабатывает.
    """
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            return json.loads(text[i:j + 1])
        raise


def _openai_chat(url: str, headers: dict, body: dict, *, retries: int = 3) -> str:
    """POST в /chat/completions с устойчивостью к бесплатным шлюзам.

    Бесплатные модели OpenRouter живут в общем пуле и часто отдают 429
    ("temporarily rate-limited"): иногда как HTTP-статус, иногда как 200 с
    телом {"error": {...}}. Здесь и то, и другое распознаём и ретраим с
    паузой (учитываем retry_after), чтобы письмо не падало на разовом лимите.
    """
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    last = ""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < retries:
                last = f"HTTP 429 {text[:120]}"
                time.sleep(min(2 ** attempt, 20)); continue
            raise RuntimeError(f"OpenAI HTTP {e.code}: {text[:300]}") from e
        err = d.get("error")
        if err:
            code, msg = err.get("code"), (err.get("message") or "")
            if code == 429 and attempt < retries:
                wait = (err.get("metadata") or {}).get("retry_after_seconds") or 2 ** attempt
                last = msg
                time.sleep(min(float(wait), 25)); continue
            raise RuntimeError(f"LLM error {code}: {msg[:300]}")
        return d["choices"][0]["message"]["content"] or ""
    raise RuntimeError(f"LLM лимит (429) не отпустил за {retries} попыток: {last[:200]}")


def _tailor_openai(vacancy: dict, master_md: str, score_hint: str | None) -> TailorResult | None:
    """Генерация через OpenAI Chat Completions (чистый urllib, без пакета openai).

    Работает и с реальным OpenAI, и с бесплатными OpenAI-совместимыми шлюзами
    (OpenRouter и пр.). Признак шлюза — модель вида ``vendor/model[:free]`` (со слешем):
    такие не понимают ни ``max_completion_tokens``, ни строгий ``json_schema``, поэтому
    для них шлём ``max_tokens`` и мягкий ``json_object``.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    model = os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)
    compat = "/" in model  # OpenRouter/совместимый шлюз, а не api.openai.com
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_user(vacancy, master_md, score_hint)},
        ],
    }
    max_out = int(os.environ.get("OPENAI_MAX_TOKENS", "6000"))
    if compat:
        body["max_tokens"] = max_out
        # json_schema strict у большинства free-моделей не поддержан → мягкий json_object
        # (системный промпт уже требует JSON с нужными полями).
        body["response_format"] = {"type": "json_object"}
    else:
        # max_completion_tokens (а не max_tokens) — иначе reasoning-модели (gpt-5) ругаются.
        body["max_completion_tokens"] = max_out
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "tailor", "strict": True, "schema": _SCHEMA},
        }
    # У gpt-5/o-моделей глубина раздумий сильно влияет на скорость: minimal ≈ 9 сек,
    # default ≈ 40+ сек. Для интерактивного бота по умолчанию minimal. Параметр шлём
    # ТОЛЬКО reasoning-моделям (gpt-4.1 его не принимает).
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "minimal")
    if compat:
        # OpenRouter: короткие раздумья reasoning-моделей (gpt-oss) — быстрее и без пустого ответа.
        body["reasoning"] = {"effort": {"minimal": "low"}.get(effort, effort) or "low"}
    elif effort and model.startswith(("gpt-5", "o1", "o3", "o4")):
        body["reasoning_effort"] = effort
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if compat:
        # OpenRouter просит указывать источник запроса (для бесплатной маршрутизации);
        # для прочих шлюзов заголовки безвредны.
        headers["HTTP-Referer"] = "https://github.com/sunpavel/findwork"
        headers["X-Title"] = "findwork"
    url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    # На free-шлюзе — стрим (иначе медленная модель отдаёт пустое тело по таймауту).
    content = llm._post_stream(url, headers, body) if compat else _openai_chat(url, headers, body)
    return _result_from_json(_loads_lenient(content), f"{model}")


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
    cover = format_cover_letter(
        "Здравствуйте!\n\n"
        f"Заинтересовала ваша вакансия «{name}» в {employer}: за 16+ лет я выстраивал "
        "коммерческий и маркетинговый блок в IT/SaaS, девелопменте и сетевом ритейле.\n\n"
        "Чем подкреплён опыт:\n"
        "— вывод продукта на рынок: вывел ERP-продукт в Топ-5 рынка, план выручки 150 млн ₽;\n"
        "— масштабирование: федеральная сеть с 3 до 15 объектов, +40% средний чек, +50% поток;\n"
        "— рост P&L: прибыль компании со 150 млн до 1 млрд ₽, доля e-commerce с 2% до 8%, "
        "работа в логике ROMI/CAC/LTV.\n\n"
        "Строю команды и системы на данных, а не тушу пожары. Буду рад обсудить, чем могу "
        "быть полезен вашей команде."
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
