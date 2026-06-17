#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP-сервис скоринга релевантности — для интеграции с n8n (или любым клиентом).

Зачем: HH-поиск стабильно работает из твоего n8n (solarn8n.pro), а скоринг/профиль —
здесь. Пусть n8n тянет вакансии из HH (как он уже умеет), а оценку релевантности и отбор
в дайджест делает этот сервис. Без зависимостей (стандартная библиотека).

Запуск:
    python3 src/score_api.py            # слушает 0.0.0.0:8088 (порт из env PORT)

Эндпоинты:
    GET  /health                 → {"ok": true}
    POST /score                  → принимает либо одну вакансию, либо {"vacancies":[...]}
         тело (одна):   {"title": "...", "description": "...", "salary": {"from":..,"to":..}}
         тело (пачка):  {"vacancies": [{"id","title","description","salary","company","url","area"}, ...]}
         ответ (пачка): {"results": [{...вакансия, "score","verdict","best_role","matched"}],
                          отсортировано по score, по умолчанию только score >= порога дайджеста}
         ?all=1                  → вернуть все, без отсечения по порогу

Формат вакансии совпадает со схемой источников (src/sources.py), так что ответ HH из n8n
можно подавать почти как есть (нужны поля title/name, description, salary).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relevance import load_profile, score_vacancy  # noqa: E402

PROFILE = load_profile()
DIGEST_MIN = PROFILE["thresholds"]["digest"]


def _score_one(vac: dict) -> dict:
    title = vac.get("title") or vac.get("name") or ""
    desc = vac.get("description") or ""
    res = score_vacancy(title, desc, vac.get("salary"), PROFILE)
    out = dict(vac)
    out.update({
        "score": res.score,
        "verdict": res.verdict,
        "best_role": res.best_role,
        "matched": res.matched_skills[:10],
        "missing": res.missing_top_skills[:6],
        "salary_note": res.salary_note,
    })
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            return self._json(200, {"ok": True, "digest_threshold": DIGEST_MIN})
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/score":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"bad json: {e}"})

        return_all = "all=1" in (self.path.split("?", 1)[1] if "?" in self.path else "")

        if isinstance(data, dict) and "vacancies" in data:
            scored = [_score_one(v) for v in data["vacancies"]]
            if not return_all:
                scored = [s for s in scored if s["score"] >= DIGEST_MIN]
            scored.sort(key=lambda s: s["score"], reverse=True)
            return self._json(200, {"count": len(scored), "results": scored})

        # одна вакансия
        return self._json(200, _score_one(data if isinstance(data, dict) else {}))

    def log_message(self, *_):  # тише в логах
        pass


def main() -> int:
    port = int(os.environ.get("PORT", "8088"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"score_api на http://0.0.0.0:{port}  (порог дайджеста: {DIGEST_MIN})")
    print(f"профиль: {PROFILE['candidate']['name']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
