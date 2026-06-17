#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор авто-отклика под конкретную вакансию.

Сценарий (по решению кандидата): ты выбираешь вакансию на hh.ru → бот под неё
создаёт релевантное резюме на основе твоих резюме, пишет сопроводительное и сам
откликается этим резюме.

Поток:
  вакансия (url/id)
    → читаем вакансию (эмуляция приложения)
    → скоринг релевантности (ядро relevance.py) — для подсказки и фильтра
    → адаптация: tailor.py (Claude API или шаблон) → правки резюме + письмо
    → резюме под вакансию (режим APPLY_RESUME_MODE)
    → отклик POST /negotiations
    → лог + учёт дневного лимита

Контроль:
  • пауза — state/control.json {"paused": true/false}; команды /pause, /resume бота;
  • дневной лимит — APPLY_DAILY_LIMIT (по умолчанию 30);
  • анти-дубль — не откликаемся повторно на ту же вакансию;
  • dry-run — всё считаем и показываем, но НИЧЕГО не создаём и не отправляем.

Режимы резюме (APPLY_RESUME_MODE):
  • clone (по умолчанию) — НОВОЕ резюме под вакансию на основе базового;
  • update — правим базовое резюме под вакансию (без размножения резюме);
  • existing — откликаемся базовым резюме как есть (адаптируем только письмо).

Использование:
  python3 src/apply.py <url_или_id> [--dry-run]
  python3 src/apply.py --pause | --resume | --status
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # запуск из любого места

import hh_app
import tailor as tailor_mod
from relevance import load_profile, score_vacancy

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
CONTROL_FILE = STATE_DIR / "control.json"
LOG_FILE = STATE_DIR / "applications.jsonl"


# --- Контроль (пауза, лимит, дедуп) -----------------------------------------

def _load_control() -> dict:
    if CONTROL_FILE.exists():
        try:
            return json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"paused": False}


def _save_control(ctrl: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    CONTROL_FILE.write_text(json.dumps(ctrl, ensure_ascii=False, indent=2), encoding="utf-8")


def is_paused() -> bool:
    return bool(_load_control().get("paused"))


def set_paused(value: bool) -> None:
    ctrl = _load_control()
    ctrl["paused"] = value
    _save_control(ctrl)


def _log_entries() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    out = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out


def _applied_today_count() -> int:
    today = dt.date.today().isoformat()
    return sum(1 for e in _log_entries()
               if e.get("status") == "applied" and e.get("ts", "").startswith(today))


def _already_applied(vacancy_id: str) -> bool:
    vid = str(vacancy_id)
    return any(e.get("vacancy_id") == vid and e.get("status") == "applied"
               for e in _log_entries())


def _append_log(entry: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    entry["ts"] = dt.datetime.now().isoformat(timespec="seconds")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def daily_limit() -> int:
    try:
        return int(os.environ.get("APPLY_DAILY_LIMIT", "30"))
    except ValueError:
        return 30


# --- Результат отклика -------------------------------------------------------

@dataclass
class ApplyResult:
    ok: bool
    vacancy_id: str
    title: str = ""
    company: str = ""
    score: int | None = None
    resume_id: str | None = None
    cover_letter: str = ""
    tailor_source: str = ""
    message: str = ""        # человекочитаемый итог
    notes: list[str] = field(default_factory=list)


def _vacancy_text(vacancy: dict) -> tuple[str, str]:
    """(title, description_text) для скоринга."""
    title = vacancy.get("name", "")
    desc = tailor_mod._strip_html(vacancy.get("description", ""))
    key_skills = " ".join(s.get("name", "") for s in vacancy.get("key_skills") or [])
    return title, f"{desc} {key_skills}".strip()


def _vacancy_salary(vacancy: dict) -> dict | None:
    sal = vacancy.get("salary")
    if not sal:
        return None
    return {"from": sal.get("from"), "to": sal.get("to"),
            "currency": sal.get("currency") or "RUR"}


def _pick_base_resume_id() -> str:
    """Базовое резюме: из HH_BASE_RESUME_ID или первое из списка соискателя."""
    env_id = os.environ.get("HH_BASE_RESUME_ID")
    if env_id:
        return env_id
    resumes = hh_app.list_resumes()
    if not resumes:
        raise hh_app.HHAppError("у соискателя нет резюме — нечего адаптировать")
    return resumes[0]["id"]


def apply_to(url_or_id: str, *, dry_run: bool = False,
             min_score: int | None = None) -> ApplyResult:
    """Полный цикл отклика под одну вакансию. Возвращает ApplyResult.

    min_score — не откликаться, если скор ниже порога (None = без фильтра здесь).
    """
    vid = hh_app.parse_vacancy_id(url_or_id)
    res = ApplyResult(ok=False, vacancy_id=vid)

    # 0) контроль
    if is_paused():
        res.message = "⏸ Бот на паузе (/resume чтобы снять)."
        return res
    if _already_applied(vid):
        res.message = "↩️ На эту вакансию уже откликались — пропуск."
        res.notes.append("дубль")
        return res
    limit = daily_limit()
    if not dry_run and _applied_today_count() >= limit:
        res.message = f"🚦 Достигнут дневной лимит откликов ({limit}). Отклик отложен."
        return res

    # 1) вакансия
    vacancy = hh_app.get_vacancy(vid)
    res.title = vacancy.get("name", "")
    res.company = (vacancy.get("employer") or {}).get("name", "")

    # 2) скоринг
    profile = load_profile()
    title, text = _vacancy_text(vacancy)
    score = score_vacancy(title, text, _vacancy_salary(vacancy), profile)
    res.score = score.score
    if min_score is not None and score.score < min_score:
        res.message = (f"🔻 Скор {score.score}/100 ниже порога {min_score} — отклик не отправлен.")
        res.notes.append("ниже порога")
        return res

    # 3) адаптация резюме + сопроводительное
    tr = tailor_mod.tailor(
        vacancy,
        score_hint=score.explain(),
        matched_skills=score.matched_skills,
    )
    res.cover_letter = tr.cover_letter
    res.tailor_source = tr.source
    res.notes += tr.notes

    if dry_run:
        res.ok = True
        res.message = (f"[dry-run] Готов отклик: {res.title} — {res.company} "
                       f"(скор {score.score}). Резюме и отправка не выполнялись.")
        return res

    # 4) резюме под вакансию
    mode = os.environ.get("APPLY_RESUME_MODE", "clone").lower()
    base_id = _pick_base_resume_id()
    if mode == "existing":
        resume_id = base_id
        res.notes.append("режим existing — базовое резюме без правок")
    elif mode == "update":
        hh_app.update_resume(base_id, tr.resume_overrides)
        resume_id = base_id
        res.notes.append("режим update — базовое резюме обновлено под вакансию")
    else:  # clone
        resume_id = hh_app.clone_resume(base_id, tr.resume_overrides)
        res.notes.append(f"режим clone — создано резюме {resume_id} под вакансию")
    res.resume_id = resume_id

    # вежливая пауза перед действием, чтобы не выглядеть ботом-спамером
    time.sleep(float(os.environ.get("APPLY_PAUSE_SEC", "2")))

    # 5) отклик
    hh_app.apply_to_vacancy(vid, resume_id, tr.cover_letter)

    # 6) лог
    _append_log({
        "status": "applied", "vacancy_id": vid, "title": res.title,
        "company": res.company, "score": score.score, "resume_id": resume_id,
        "tailor": tr.source, "mode": mode,
    })
    res.ok = True
    res.message = (f"✅ Отклик отправлен: {res.title} — {res.company} "
                   f"(скор {score.score}, резюме {resume_id}, текст: {tr.source}).")
    return res


# --- CLI ---------------------------------------------------------------------

def _print_status() -> None:
    ctrl = _load_control()
    today = _applied_today_count()
    print(f"Пауза: {'ДА ⏸' if ctrl.get('paused') else 'нет ▶️'}")
    print(f"Откликов сегодня: {today} / {daily_limit()}")
    print(f"Всего в логе: {sum(1 for e in _log_entries() if e.get('status') == 'applied')}")
    print(f"Режим резюме: {os.environ.get('APPLY_RESUME_MODE', 'clone')}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Авто-отклик под вакансию (findwork)")
    p.add_argument("target", nargs="?", help="ссылка на вакансию hh.ru или её id")
    p.add_argument("--dry-run", action="store_true", help="посчитать и показать, ничего не отправлять")
    p.add_argument("--min-score", type=int, default=None, help="не откликаться ниже порога")
    p.add_argument("--pause", action="store_true", help="поставить бота на паузу")
    p.add_argument("--resume", action="store_true", help="снять паузу")
    p.add_argument("--status", action="store_true", help="показать статус")
    args = p.parse_args(argv)

    if args.pause:
        set_paused(True); print("⏸ Поставлено на паузу."); return 0
    if args.resume:
        set_paused(False); print("▶️ Пауза снята."); return 0
    if args.status:
        _print_status(); return 0
    if not args.target:
        p.error("укажи ссылку/id вакансии, либо --pause/--resume/--status")

    try:
        res = apply_to(args.target, dry_run=args.dry_run, min_score=args.min_score)
    except hh_app.HHAppError as e:
        print(f"Ошибка HH: {e}")
        if e.body:
            print(e.body[:500])
        return 1
    print(res.message)
    for n in res.notes:
        print(f"  · {n}")
    return 0 if res.ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
