#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика n8n-деплоя: проверяет N8N_KEY из .env, перечисляет воркфлоу и показывает,
где в них лежат HH-креды (тело узла vs n8n-credential). Ничего не меняет.

Запуск:  .venv/bin/python scripts/diag_n8n.py   (или python3 scripts/diag_n8n.py)
"""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    env = {}
    if not Path(path).exists():
        return env
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.replace("export ", "").strip()
        v = v.strip()
        if (v[:1], v[-1:]) in (('"', '"'), ("'", "'")):
            v = v[1:-1]
        env[k] = v
    return env


def main():
    env = load_env()
    url = (env.get("N8N_URL", "https://solarn8n.pro")).rstrip("/")
    key = env.get("N8N_KEY", "")

    # .env-санити
    raw = (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []
    n_key_lines = sum(1 for ln in raw if ln.strip().startswith("N8N_KEY="))
    print(f"N8N_URL: {url}")
    print(f"N8N_KEY: {'ПУСТО' if not key else key[:10] + '…' + key[-6:]} "
          f"(len={len(key)}, строк N8N_KEY в .env={n_key_lines})")
    if " " in key or n_key_lines != 1:
        print("⚠️  N8N_KEY выглядит битым (пробел внутри или не одна строка) — поправь .env.")
    if not key:
        print("❌ нет N8N_KEY — дальше нет смысла."); return 1

    def api(path):
        req = urllib.request.Request(f"{url}/api/v1{path}",
                                     headers={"X-N8N-API-KEY": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    try:
        data = api("/workflows")
    except Exception as e:  # noqa: BLE001
        print(f"❌ n8n API не ответил ({e}). Скорее всего N8N_KEY неверный/битый.")
        return 1
    items = data.get("data") if isinstance(data, dict) else data
    print(f"\n✅ ключ работает. Воркфлоу ({len(items)}):")
    for w in items:
        print(f"  id={w.get('id')}  active={w.get('active')}  name={w.get('name')!r}")

    print("\nГде HH-креды в подходящих воркфлоу:")
    for w in items:
        nm = (w.get("name") or "")
        if "findwork" not in nm.lower() and "hh" not in nm.lower():
            continue
        full = api(f"/workflows/{w['id']}")
        print(f"\n  ворк {w['id']} {nm!r}:")
        for n in full.get("nodes", []) or []:
            name = n.get("name", "")
            if "token" not in name.lower():
                continue
            params = n.get("parameters") or {}
            bp = (params.get("bodyParameters") or {}).get("parameters") or []
            bnames = [p.get("name") for p in bp]
            has_cid = any(p.get("name") == "client_id" and p.get("value") for p in bp)
            creds = n.get("credentials")
            print(f"    • {name!r}: bodyParams={bnames} client_id_в_теле={has_cid} "
                  f"credentials={list(creds) if creds else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
