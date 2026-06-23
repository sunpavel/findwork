#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Поднимает («обновляет дату») выбранные резюме на hh.ru — POST /resumes/{id}/publish.

Запускается systemd-таймером findwork-bump.timer (ежедневно в 10:00, см. scripts/setup.sh).
HH разрешает поднимать резюме не чаще раза в 4 часа, поэтому раз в сутки — безопасно.

Какие резюме поднимать:
  • переменная окружения HH_BUMP_RESUME_IDS — id или полные URL через запятую;
  • если не задана — берётся DEFAULT_IDS ниже.

Запуск вручную:
  python3 scripts/bump_resumes.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import hh_app  # noqa: E402

# Резюме кандидата по умолчанию (можно переопределить через HH_BUMP_RESUME_IDS).
DEFAULT_IDS = [
    "de636ec0ff0967221d0039ed1f6a7867313771",
    "c93ac21bff0bd1b6390039ed1f76344d665259",
]


def _resume_ids() -> list[str]:
    raw = os.environ.get("HH_BUMP_RESUME_IDS", "").strip()
    items = [x.strip() for x in raw.split(",") if x.strip()] or DEFAULT_IDS
    out: list[str] = []
    for it in items:
        m = re.search(r"/resume/([0-9a-zA-Z]+)", it)
        rid = m.group(1) if m else it
        if rid and rid not in out:
            out.append(rid)
    return out


def main() -> int:
    ids = _resume_ids()
    ok = 0
    for rid in ids:
        try:
            hh_app.publish_resume(rid)
            print(f"OK: поднято резюме {rid}")
            ok += 1
        except hh_app.HHAppError as e:
            # 429 = ещё не прошло 4 часа с прошлого подъёма — не ошибка пайплайна.
            note = " (рано — HH поднимает раз в 4ч)" if e.status == 429 else ""
            print(f"FAIL: {rid} → {e}{note}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL: {rid} → {type(e).__name__}: {e}", file=sys.stderr)
    print(f"итог: поднято {ok}/{len(ids)}")
    return 0 if ok == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
