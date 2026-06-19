#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создаёт/обновляет error-воркфлоу для скана вакансий и привязывает его как errorWorkflow.

Зачем: скан (hh.ru — findwork) гоняется по расписанию; если прогон падает (токен HH,
сеть, код-нода), n8n молча не отправляет ничего. Этот воркфлоу — Error Trigger → Telegram:
при сбое любого воркфлоу, у которого в настройках указан errorWorkflow=<этот id>, в чат
прилетает «⚠️ Скан вакансий не отработал» с узлом и текстом ошибки.

Запуск:
  N8N_URL=... N8N_KEY=... [TARGET_WF_ID=27sTe6NMZC1yshqm] [CHAT_ID=109790719] \
  python3 tools/build_n8n_error_workflow.py
"""
import json
import os
import sys
import urllib.request
import uuid

N8N_URL = os.environ.get("N8N_URL", "https://solarn8n.pro").rstrip("/")
N8N_KEY = os.environ.get("N8N_KEY", "")
TELEGRAM_CRED = {"id": "C6kRfnWdYvqjRNrb", "name": "SolarHH_bot"}
CHAT_ID = os.environ.get("CHAT_ID", "109790719")
TARGET_WF_ID = os.environ.get("TARGET_WF_ID", "27sTe6NMZC1yshqm")
WF_NAME = "findwork: алерт о сбое скана"
ALLOWED_SETTINGS = {"saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
                    "saveDataSuccessExecution", "executionTimeout", "errorWorkflow",
                    "timezone", "executionOrder"}


def _api(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{N8N_URL}/api/v1{path}", data=data, method=method,
                                 headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def _nid():
    return str(uuid.uuid4())


def build_error_wf():
    text = ("=⚠️ Скан вакансий не отработал\n"
            "Воркфлоу: {{ $json.workflow.name }}\n"
            "Узел: {{ $json.execution.lastNodeExecuted }}\n"
            "Ошибка: {{ ($json.execution.error || {}).message }}")
    nodes = [
        {"id": _nid(), "name": "Error Trigger", "type": "n8n-nodes-base.errorTrigger",
         "typeVersion": 1, "position": [-200, 0], "parameters": {}},
        {"id": _nid(), "name": "Telegram: алерт", "type": "n8n-nodes-base.telegram",
         "typeVersion": 1.2, "position": [60, 0],
         "parameters": {"chatId": "=" + CHAT_ID, "text": text,
                        "additionalFields": {"appendAttribution": False}},
         "credentials": {"telegramApi": TELEGRAM_CRED}},
    ]
    conns = {"Error Trigger": {"main": [[{"node": "Telegram: алерт", "type": "main", "index": 0}]]}}
    return {"name": WF_NAME, "nodes": nodes, "connections": conns,
            "settings": {"executionOrder": "v1", "timezone": "Europe/Moscow"}}


def main():
    if not N8N_KEY:
        sys.exit("Задай N8N_KEY.")
    wf = build_error_wf()
    existing = next((w["id"] for w in _api("/workflows?limit=200").get("data", [])
                     if w.get("name") == WF_NAME), None)
    if existing:
        _api(f"/workflows/{existing}", "PUT", wf)
        wf_id = existing
        print("ОБНОВЛЁН error-wf:", wf_id)
    else:
        wf_id = _api("/workflows", "POST", wf).get("id")
        print("СОЗДАН error-wf:", wf_id)

    # Привязываем как errorWorkflow к скану (settings.errorWorkflow), не трогая ноды/креды.
    d = _api(f"/workflows/{TARGET_WF_ID}")
    s = {k: v for k, v in (d.get("settings") or {}).items() if k in ALLOWED_SETTINGS}
    s["errorWorkflow"] = wf_id
    payload = {"name": d["name"], "nodes": d["nodes"], "connections": d["connections"], "settings": s}
    if d.get("staticData"):
        payload["staticData"] = d["staticData"]
    _api(f"/workflows/{TARGET_WF_ID}", "PUT", payload)
    _api(f"/workflows/{TARGET_WF_ID}/activate", "POST")
    print(f"errorWorkflow привязан к {TARGET_WF_ID}; открой: {N8N_URL}/workflow/{wf_id}")


if __name__ == "__main__":
    main()
