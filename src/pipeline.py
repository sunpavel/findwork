#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пайплайн утреннего дайджеста вакансий.

Поток: источник → дедуп по виденным id → скоринг релевантности → топ-N →
сообщение в Telegram (или печать в консоль).

Запуск (офлайн-демо на тестовых вакансиях, без отправки):
    python3 src/pipeline.py --source sample --dry-run

Боевой запуск по утрам (на VPS, cron/systemd-timer):
    python3 src/pipeline.py --source hh --send

Состояние виденных вакансий хранится в state/seen.json (в .gitignore).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path

from relevance import load_profile, score_vacancy
from sources import get_source
from notify import send_telegram

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SEEN_PATH = STATE_DIR / "seen.json"


def _load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
    return set()


def _save_seen(seen: set[str]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def _fmt_salary(salary: dict | None) -> str:
    if not salary or not (salary.get("from") or salary.get("to")):
        return "з/п не указана"
    lo, hi = salary.get("from"), salary.get("to")
    cur = salary.get("currency", "RUR").replace("RUR", "₽")
    if lo and hi:
        body = f"{lo:,}–{hi:,}".replace(",", " ")
    else:
        body = f"от {lo:,}".replace(",", " ") if lo else f"до {hi:,}".replace(",", " ")
    return f"{body} {cur}"


def build_digest(scored: list[tuple[dict, object]], limit: int) -> str:
    """Собирает дайджест в HTML (parse_mode=HTML). Динамические поля экранируем —
    иначе спецсимволы в названиях вакансий (`_`, `<`, `&` ...) ломают отправку."""
    e = html.escape
    today = dt.date.today().strftime("%d.%m.%Y")
    lines = [f"<b>🗞 Вакансии на {today}</b> — {min(len(scored), limit)} релевантных\n"]
    for vac, res in scored[:limit]:
        matched = e(", ".join(res.matched_skills[:6]) or "—")
        lines.append(
            f"<b>{res.score}/100</b> · {e(vac.get('title', ''))}\n"
            f"🏢 {e(vac.get('company') or '—')} · 📍 {e(vac.get('area') or '—')} · "
            f"💰 {e(_fmt_salary(vac.get('salary')))}\n"
            f"🎯 роль: {e(res.best_role)} · ✓ {matched}\n"
            f"🔗 {e(vac.get('url', ''))}\n"
        )
    lines.append("<i>Ответь номером/ссылкой «резюме» или «отклик» — подготовлю.</i>")
    return "\n".join(lines)


def build_digest_smart(scored: list[tuple[dict, object]], limit: int) -> str:
    """Дайджест по LLM-релевантности (relevance_llm.FitResult): показываем не «совпавшие
    слова», а почему вакансия в уровень и по опыту + честный подвох и уровень."""
    e = html.escape
    today = dt.date.today().strftime("%d.%m.%Y")
    lines = [f"<b>🗞 Вакансии на {today}</b> — {min(len(scored), limit)} под твой профиль\n"]
    for vac, fr in scored[:limit]:
        title = vac.get("title") or vac.get("name", "")
        block = (f"<b>{fr.score}/100</b> · {e(title)}\n"
                 f"🏢 {e(vac.get('company') or '—')} · 📍 {e(vac.get('area') or '—')} · "
                 f"💰 {e(_fmt_salary(vac.get('salary')))}\n")
        if fr.why:
            block += f"💡 {e(fr.why[:240])}\n"
        if fr.gaps:
            block += f"⚠️ {e('; '.join(fr.gaps[:2])[:200])}\n"
        if fr.level_match and fr.level_match != "в уровень":
            block += f"📊 уровень: {e(fr.level_match)}\n"
        block += f"🔗 {e(vac.get('url', ''))}\n"
        lines.append(block)
    lines.append("<i>Ответь ссылкой на вакансию — подготовлю резюме и письмо.</i>")
    return "\n".join(lines)


def build_list_text(scored: list[tuple[dict, object]], limit: int, seen: set[str]) -> str:
    """Плоский (не-HTML) список вакансий для вывода в консоль командой `--list`.

    В отличие от дайджеста: ничего не экранируем (это терминал, а не Telegram), нумеруем
    и помечаем уже виденные — чтобы было видно, что нового, а что уже проходило ранее.
    """
    shown = scored[:limit] if limit and limit > 0 else scored
    head = f"Релевантных вакансий: {len(scored)}"
    if len(shown) < len(scored):
        head += f" (показаны первые {len(shown)}; см. --limit)"
    lines = [head]
    for i, (vac, res) in enumerate(shown, 1):
        title = vac.get("title") or vac.get("name", "")
        mark = "  [виденная]" if vac.get("id") in seen else ""
        matched = ", ".join(res.matched_skills[:6]) or "—"
        lines.append(
            f"\n{i:>2}. {res.score}/100 · {title}{mark}\n"
            f"    🏢 {vac.get('company') or '—'} · 📍 {vac.get('area') or '—'} · "
            f"💰 {_fmt_salary(vac.get('salary'))}\n"
            f"    🎯 роль: {res.best_role} · ✓ {matched}\n"
            f"    🔗 {vac.get('url', '')}"
        )
    return "\n".join(lines)


def list_vacancies(source_name: str, limit: int, unseen_only: bool) -> int:
    """Только-просмотр: собирает вакансии, скорит keyword-скорингом и печатает релевантные.

    Ничего не отправляет в Telegram и не трогает state/ — поэтому LLM-судью здесь не зовём
    (это «полистать», а не «разослать дайджест»): быстро, офлайн-безопасно, повторяемо.
    По умолчанию показываем всё релевантное (включая виденное, с пометкой); с --unseen —
    только новые вакансии.
    """
    profile = load_profile()
    vacancies = collect(source_name, profile)
    seen = _load_seen()

    pool = [v for v in vacancies if v["id"] not in seen] if unseen_only else vacancies
    th = profile["thresholds"]["digest"]
    scored = [(v, r) for v in pool
              if (r := score_vacancy(v.get("title") or v.get("name", ""),
                                     v.get("description", ""), v.get("salary"), profile)).score >= th]
    scored.sort(key=lambda pair: pair[1].score, reverse=True)

    scope = "новых " if unseen_only else ""
    print(f"Источники: {source_name} · всего {len(vacancies)} · {scope}релевантных: {len(scored)} · keyword-скоринг")
    if not scored:
        print("Релевантных вакансий не найдено.")
        return 0

    print("\n" + build_list_text(scored, limit, seen) + "\n")
    print("[list] только просмотр — состояние не изменено, ничего не отправлено")
    return 0


def collect(source_names: str, profile: dict) -> list[dict]:
    """Собирает вакансии из одного или нескольких источников (через запятую).

    Падение одного источника не роняет сбор — остальные отрабатывают. Дедуп по id
    выполняется и между источниками.
    """
    names = [s.strip() for s in source_names.split(",") if s.strip()]
    all_v, seen_ids = [], set()
    for name in names:
        try:
            vs = get_source(name)(profile=profile)
            print(f"  источник {name}: {len(vs)} вакансий")
        except Exception as e:  # noqa: BLE001 — источник может быть не настроен (напр. hh без авторизации)
            print(f"  источник {name}: пропущен ({e})")
            continue
        for v in vs:
            if v["id"] not in seen_ids:
                seen_ids.add(v["id"])
                all_v.append(v)
    return all_v


def _applied_hh_ids() -> set[str]:
    """Сырые HH-id вакансий с уже сделанным откликом (история HH: ручные + через бота).

    Пусто при отсутствии токена/ошибке — фильтр просто не применяется, дайджест не падает.
    """
    try:
        import hh_app  # noqa: PLC0415
        return hh_app.applied_vacancy_ids()
    except Exception as e:  # noqa: BLE001 — нет авторизации/сети: деградируем без фильтра
        print(f"  история откликов HH недоступна ({e}) — фильтр уже-откликнутых пропущен")
        return set()


def _hh_id_of(v: dict) -> str | None:
    """HH-id вакансии, если он есть: из нормализованного id (hh-<id>) или из ссылки/описания
    (канальные посты часто содержат hh.ru/vacancy/<id>)."""
    vid = v.get("id", "") or ""
    if vid.startswith("hh-"):
        return vid[3:]
    for field in (v.get("url", ""), v.get("description", "")):
        m = re.search(r"/vacancy/(\d+)", field or "")
        if m:
            return m.group(1)
    return None


def run(source_name: str, send: bool, dry_run: bool, limit: int) -> int:
    import os  # noqa: PLC0415
    profile = load_profile()

    vacancies = collect(source_name, profile)
    seen = _load_seen()
    new_vacs = [v for v in vacancies if v["id"] not in seen]

    # Исключаем вакансии, на которые уже откликнулись на hh.ru (ручные + через бота) —
    # источник правды history /negotiations. Делаем ДО судьи (экономим токены) и помечаем
    # их виденными, чтобы не возвращались. Отключается EXCLUDE_APPLIED=0.
    applied_seen_ids: list[str] = []
    if os.environ.get("EXCLUDE_APPLIED", "1").strip().lower() not in ("0", "false", "no"):
        applied = _applied_hh_ids()
        if applied:
            applied_seen_ids = [v["id"] for v in new_vacs if _hh_id_of(v) in applied]
            if applied_seen_ids:
                drop = set(applied_seen_ids)
                new_vacs = [v for v in new_vacs if v["id"] not in drop]
                print(f"  исключено уже-откликнутых на HH: {len(applied_seen_ids)} "
                      f"(в истории откликов {len(applied)})")

    # Умная релевантность (LLM-судья по мастер-резюме) — если доступен LLM и не выключено
    # RELEVANCE_LLM=0. Иначе откатываемся на keyword-скоринг. Помечаем виденными ВСЕ
    # рассмотренные вакансии (в smart-режиме — чтобы не пере-судить их и не жечь токены).
    smart = None
    if os.environ.get("RELEVANCE_LLM", "1").strip().lower() not in ("0", "false", "no"):
        try:
            import llm  # noqa: PLC0415
            import relevance_llm  # noqa: PLC0415
            if llm.has_provider(llm.default_provider()):
                smart = relevance_llm.rank_smart(new_vacs, profile)
        except Exception as e:  # noqa: BLE001 — нет LLM/ключа: тихо на keyword
            print(f"  LLM-релевантность недоступна ({e}) — keyword-скоринг")

    if smart is not None:
        scored = smart
        digest = build_digest_smart(scored, limit)
        to_mark = [v["id"] for v in new_vacs]            # все рассмотренные — не пере-судим
        mode = "LLM-судья по мастер-резюме"
    else:
        th = profile["thresholds"]["digest"]
        kw = [(v, r) for v in new_vacs
              if (r := score_vacancy(v["title"], v.get("description", ""), v.get("salary"), profile)).score >= th]
        kw.sort(key=lambda pair: pair[1].score, reverse=True)
        scored, digest = kw, build_digest(kw, limit)
        to_mark = [v["id"] for v, _ in kw]
        mode = "keyword-скоринг"

    print(f"Источники: {source_name} · всего {len(vacancies)} · новых релевантных: {len(scored)} · {mode}")
    if not scored:
        print("Новых релевантных вакансий нет — дайджест не отправляется.")
        if not dry_run:  # всё равно помечаем рассмотренные, чтобы не гонять их повторно
            seen.update(to_mark); seen.update(applied_seen_ids); _save_seen(seen)
        return 0

    print("\n" + digest + "\n")

    if send and not dry_run:
        ok = send_telegram(digest, parse_mode="HTML")
        print("Telegram: отправлено" if ok else "Telegram: не отправлено")

    if not dry_run:
        seen.update(to_mark)
        seen.update(applied_seen_ids)
        _save_seen(seen)
        print(f"Помечено как виденные: +{len(to_mark)} (всего {len(seen)})")
    else:
        print("[dry-run] состояние не изменено, ничего не отправлено")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Утренний дайджест вакансий findwork")
    p.add_argument("--source", default="sample",
                   help="источник(и) через запятую: sample | trudvsem | hh | 'trudvsem,hh'")
    p.add_argument("--send", action="store_true", help="отправить дайджест в Telegram")
    p.add_argument("--dry-run", action="store_true", help="не менять состояние и не отправлять")
    p.add_argument("--limit", type=int, default=10, help="сколько вакансий в дайджест/список (0 — все)")
    p.add_argument("--list", action="store_true", dest="list_only",
                   help="только показать релевантные вакансии в консоли (без отправки и без изменения состояния)")
    p.add_argument("--unseen", action="store_true",
                   help="с --list: показать только новые (не виденные ранее) вакансии")
    args = p.parse_args()
    if args.list_only:
        return list_vacancies(args.source, args.limit, args.unseen)
    return run(args.source, args.send, args.dry_run, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
