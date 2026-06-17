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
import json
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
    today = dt.date.today().strftime("%d.%m.%Y")
    lines = [f"*🗞 Вакансии на {today}* — {min(len(scored), limit)} релевантных\n"]
    for vac, res in scored[:limit]:
        matched = ", ".join(res.matched_skills[:6]) or "—"
        lines.append(
            f"*{res.score}/100* · {vac['title']}\n"
            f"🏢 {vac.get('company', '—')} · 📍 {vac.get('area', '—')} · 💰 {_fmt_salary(vac.get('salary'))}\n"
            f"🎯 роль: {res.best_role} · ✓ {matched}\n"
            f"🔗 {vac.get('url', '')}\n"
        )
    lines.append("_Ответь номером/ссылкой «резюме» или «отклик» — подготовлю._")
    return "\n".join(lines)


def run(source_name: str, send: bool, dry_run: bool, limit: int) -> int:
    profile = load_profile()
    digest_threshold = profile["thresholds"]["digest"]

    vacancies = get_source(source_name)(profile=profile)
    seen = _load_seen()

    scored = []
    for vac in vacancies:
        if vac["id"] in seen:
            continue
        res = score_vacancy(vac["title"], vac.get("description", ""), vac.get("salary"), profile)
        if res.score >= digest_threshold:
            scored.append((vac, res))

    scored.sort(key=lambda pair: pair[1].score, reverse=True)

    print(f"Источник: {source_name} · всего {len(vacancies)} · новых релевантных: {len(scored)}")
    if not scored:
        print("Новых релевантных вакансий нет — дайджест не отправляется.")
        return 0

    digest = build_digest(scored, limit)
    print("\n" + digest + "\n")

    if send and not dry_run:
        ok = send_telegram(digest)
        print("Telegram: отправлено" if ok else "Telegram: не отправлено")

    if not dry_run:
        seen.update(vac["id"] for vac, _ in scored)
        _save_seen(seen)
        print(f"Помечено как виденные: +{len(scored)} (всего {len(seen)})")
    else:
        print("[dry-run] состояние не изменено, ничего не отправлено")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Утренний дайджест вакансий findwork")
    p.add_argument("--source", default="sample", help="источник: sample | hh")
    p.add_argument("--send", action="store_true", help="отправить дайджест в Telegram")
    p.add_argument("--dry-run", action="store_true", help="не менять состояние и не отправлять")
    p.add_argument("--limit", type=int, default=10, help="сколько вакансий в дайджест")
    args = p.parse_args()
    return run(args.source, args.send, args.dry_run, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
