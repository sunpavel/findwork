#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика ПОСЛЕДНЕГО запуска дайджеста в n8n: что вернула каждая нода
(❌ ошибка / 0 items / N items). Помогает понять, что именно «сломалось».

Запуск:  python3 scripts/diag_scan.py
Берёт N8N_URL / N8N_KEY из .env (как deploy_n8n.sh).
"""
import json
import os
import sys
import urllib.request

WF_NAME = "hh.ru — findwork (скоринг)"


def load_env() -> dict:
    env = {}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip().lstrip("﻿")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip().replace("export ", "")] = v.strip().strip('"').strip("'")
    return env


def api(base: str, key: str, path: str):
    req = urllib.request.Request(base + path,
                                 headers={"X-N8N-API-KEY": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    env = load_env()
    base = (env.get("N8N_URL") or "https://solarn8n.pro").rstrip("/")
    key = env.get("N8N_KEY", "")
    if not key:
        sys.exit("❌ нет N8N_KEY в .env")

    wfs = api(base, key, "/api/v1/workflows?limit=250").get("data", [])
    wf = next((w for w in wfs if w.get("name") == WF_NAME), None)
    if not wf:
        sys.exit(f"❌ воркфлоу '{WF_NAME}' не найден")
    wid = wf["id"]
    print(f"воркфлоу {wid} · active={wf.get('active')}")

    execs = api(base, key, f"/api/v1/executions?workflowId={wid}&limit=1&includeData=true").get("data", [])
    if not execs:
        sys.exit("❌ запусков ещё не было (executions пуст)")
    e = execs[0]
    print(f"последний запуск: started={e.get('startedAt')} · finished={e.get('finished')} "
          f"· status={e.get('status')}")
    run = (((e.get("data") or {}).get("resultData") or {}).get("runData") or {})
    if not run:
        print("⚠️ нет runData в ответе API — открой Executions в UI n8n и глянь ноды вручную.")
        return 0

    # Сначала — ноды поиска/источников и ключевые, потом остальное.
    def items_of(r0):
        try:
            return len(((r0.get("data") or {}).get("main") or [[]])[0])
        except Exception:  # noqa: BLE001
            return 0

    hh, others = [], []
    for name, runs in run.items():
        r0 = runs[0] if runs else {}
        err = r0.get("error")
        n = items_of(r0)
        msg = ""
        if err:
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
        row = (name, n, bool(err), msg)
        (hh if (name.startswith("HH") or "facancy" in name.lower()
                or "score" in name.lower() or "канал" in name.lower() or "Merge" in name) else others).append(row)

    def show(rows):
        for name, n, err, msg in rows:
            mark = "❌ ОШИБКА" if err else ("✅ %d" % n if n else "0 items")
            print(f"  {mark:>10}  {name}" + (f"  | {msg[:90]}" if msg else ""))

    print("\n— Источники / скоринг / merge —")
    show(hh)
    print("\n— Прочие ноды —")
    show(others)
    print("\nЧитать так: HH-ноды с «0 items» или «ОШИБКА» = HH не отдаёт (бан/прокси/запрос). "
          "facancy/каналы с N items = они живы. score+dedup с N = в дайджест ушло N.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
