#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создаёт в n8n webhook-воркфлоу «findwork: LLM», через который бот из РФ ходит к
ChatGPT (платный ключ живёт в n8n-кредле, гео-блок api.openai.com не мешает).

Поток:
  Webhook(POST /findwork-llm) → [auth по X-Findwork-Token] → OpenAI(Chat) → Respond(JSON)

Контракт (его дёргает src/llm.py, провайдер "n8n"):
  ЗАПРОС  (JSON body): {"system": str, "user": str, "model": str,
                        "max_tokens": int, "json_mode": bool}
  ОТВЕТ   (JSON):      {"content": "<текст ответа модели>"}
  Заголовок X-Findwork-Token: общий секрет (если задан N8N_LLM_TOKEN при сборке).

В боте после создания задать окружение:
  N8N_LLM_URL=https://<твой-n8n>/webhook/findwork-llm
  N8N_LLM_TOKEN=<тот же секрет>          # если включал auth
  N8N_LLM_MODEL=gpt-4o                    # или оставь дефолт в воркфлоу
  WRITER_PROVIDER=n8n                     # необязательно: при заданном N8N_LLM_URL включается само

Запуск (использует тот же OpenAI-кредл, что и дайджест — «Chekanal»):
  N8N_URL=https://solarn8n.pro N8N_KEY=... [N8N_LLM_TOKEN=secret] [N8N_LLM_MODEL=gpt-4o] \
  [OPENAI_CRED_ID=uXn6hZoeLAiQJHNZ OPENAI_CRED_NAME=Chekanal] \
  [N8N_WF_ID=<id для обновления>] [N8N_ACTIVATE=1] python3 tools/build_n8n_llm_webhook.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

N8N_URL = os.environ.get("N8N_URL", "https://solarn8n.pro").rstrip("/")
N8N_KEY = os.environ.get("N8N_KEY", "")
OPENAI_CRED = {"id": os.environ.get("OPENAI_CRED_ID", "uXn6hZoeLAiQJHNZ"),
               "name": os.environ.get("OPENAI_CRED_NAME", "Chekanal")}
PATH = os.environ.get("N8N_LLM_PATH", "findwork-llm")
TOKEN = os.environ.get("N8N_LLM_TOKEN", "")
MODEL = os.environ.get("N8N_LLM_MODEL", "gpt-4o")

AUTH_JS = """
const exp = "__TOKEN__";
const h = $json.headers || {};
const got = h['x-findwork-token'] || h['X-Findwork-Token'] || '';
if (exp && got !== exp) { throw new Error('unauthorized'); }
return $input.all();
""".replace("__TOKEN__", TOKEN)

# OpenAI langchain-нода кладёт ответ по-разному в зависимости от версии — берём всё разумное.
RESP_BODY = ("={{ JSON.stringify({ content: ($json.message && $json.message.content) "
             "|| $json.text || $json.content || '' }) }}")


def nid():
    return str(uuid.uuid4())


def node(name, ntype, ver, params, pos, creds=None, extra=None):
    n = {"id": nid(), "name": name, "type": ntype, "typeVersion": ver,
         "position": pos, "parameters": params}
    if creds:
        n["credentials"] = creds
    if extra:
        n.update(extra)
    return n


def build():
    n_wh = node("Webhook", "n8n-nodes-base.webhook", 2,
                {"httpMethod": "POST", "path": PATH, "responseMode": "responseNode",
                 "options": {}}, [-600, 200], extra={"webhookId": nid()})
    n_auth = node("auth", "n8n-nodes-base.code", 2, {"jsCode": AUTH_JS}, [-400, 200])
    n_oai = node("OpenAI", "@n8n/n8n-nodes-langchain.openAi", 1.8,
                 {"modelId": {"__rl": True, "mode": "id",
                              "value": "={{ $json.body.model || '%s' }}" % MODEL},
                  "messages": {"values": [
                      {"role": "system", "content": "={{ $json.body.system }}"},
                      {"role": "user", "content": "={{ $json.body.user }}"}]},
                  "options": {"maxTokens": "={{ $json.body.max_tokens || 6000 }}"}},
                 [-180, 200], creds={"openAiApi": OPENAI_CRED},
                 extra={"onError": "continueRegularOutput"})
    n_resp = node("Respond", "n8n-nodes-base.respondToWebhook", 1.1,
                  {"respondWith": "json", "responseBody": RESP_BODY,
                   "options": {}}, [60, 200])

    nodes = [n_wh, n_auth, n_oai, n_resp]
    conn = {}

    def add(a, b):
        conn.setdefault(a["name"], {"main": [[]]})["main"][0].append(
            {"node": b["name"], "type": "main", "index": 0})

    add(n_wh, n_auth)
    add(n_auth, n_oai)
    add(n_oai, n_resp)
    return {"name": "findwork: LLM (webhook → ChatGPT)", "nodes": nodes, "connections": conn,
            "settings": {"executionOrder": "v1", "timezone": "Europe/Moscow"}}


def _api(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{N8N_URL}/api/v1{path}", data=data, method=method,
                                 headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode())


def main():
    if not N8N_KEY:
        sys.exit("Задай N8N_KEY.")
    wf = build()
    wf_id = os.environ.get("N8N_WF_ID")
    try:
        if wf_id:
            out = _api(f"/workflows/{wf_id}", "PUT", wf); print("ОБНОВЛЁН:", out.get("id"))
        else:
            out = _api("/workflows", "POST", wf); wf_id = out.get("id"); print("СОЗДАН:", wf_id)
        if os.environ.get("N8N_ACTIVATE") == "1":
            print("АКТИВИРОВАН:", _api(f"/workflows/{wf_id}/activate", "POST").get("active"))
        print(f"открой:   {N8N_URL}/workflow/{wf_id}")
        print(f"webhook:  {N8N_URL}/webhook/{PATH}")
        print("→ в боте: N8N_LLM_URL=%s/webhook/%s%s" %
              (N8N_URL, PATH, ("  N8N_LLM_TOKEN=<secret>" if TOKEN else "")))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:800]); sys.exit(1)


if __name__ == "__main__":
    main()
