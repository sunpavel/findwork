#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создаёт в n8n улучшенную копию HH-воркфлоу (НЕ трогая оригинал), выключенную.

Схема (чисто и предсказуемо):
  Schedule(09:00) / Manual → today(date) → HH «Коммерческий директор»
                                         → HH «Директор по маркетингу»
                              HH1, HH2 → Merge(append) → Скоринг+Дайджест(Code) → Telegram

Скоринг — детерминированный (профиль зашит из profile.json), отбирает score>=порога,
ранжирует и собирает один текстовый дайджест. Без LLM/Postgres в v1 (надёжно и проверяемо).

Запуск:
  N8N_URL=https://solarn8n.pro N8N_KEY=<jwt> python3 tools/build_n8n_workflow.py
"""
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "profile" / "profile.json").read_text(encoding="utf-8"))
PJSON = json.dumps(PROFILE, ensure_ascii=False)

N8N_URL = os.environ.get("N8N_URL", "https://solarn8n.pro").rstrip("/")
N8N_KEY = os.environ.get("N8N_KEY", "")
TELEGRAM_CRED = {"id": "C6kRfnWdYvqjRNrb", "name": "SolarHH_bot"}
CHAT_ID = "109790719"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")
HH_CLIENT_ID = os.environ.get("HH_CLIENT_ID", "")
HH_CLIENT_SECRET = os.environ.get("HH_CLIENT_SECRET", "")
HH_STATIC_TOKEN = os.environ.get("HH_STATIC_TOKEN", "")  # если задан — минтить не будем
_BASE_HEADERS = [
    {"name": "User-Agent", "value": BROWSER_UA},
    {"name": "HH-User-Agent", "value": "findwork/1.0 (sunpavel@mail.ru)"},
    {"name": "Accept", "value": "application/json, text/plain, */*"},
    {"name": "Accept-Language", "value": "ru-RU,ru;q=0.9"},
]
HH_HEADERS = {"parameters": _BASE_HEADERS}

HH_QUERY = """={
  "text": "%(role)s",
  "only_with_salary": "false",
  "search_field": ["name"],
  "area": 1,
  "date_from": "{{ $('today').item.json.date }}T00:00:00",
  "order_by": "publication_time",
  "page": 0,
  "per_page": 100
}"""

SCORE_JS = r'''
const PROFILE = __PROFILE__;
function norm(s){ return (s||'').toString().toLowerCase().replace(/ё/g,'е').replace(/\s+/g,' '); }
function esc(s){ return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'); }
function contains(hay, needle){
  needle = norm(needle);
  if (needle.length <= 4 && /^[\x00-\x7F]+$/.test(needle))
    return new RegExp('(?<![a-z])'+esc(needle)+'(?![a-z])').test(hay);
  return hay.indexOf(needle) !== -1;
}
function ranked(){ return Object.entries(PROFILE.skills).sort((a,b)=>b[1]-a[1]); }
function titleScore(t){ let best=0, role='—';
  for (const r of PROFILE.target_roles)
    if (r.title_keywords.some(k=>contains(t,k)) && r.weight>best){ best=r.weight; role=r.name; }
  return {score:best, role}; }
function skillsScore(x){ const rk=ranked(); const sat=rk.slice(0,12).reduce((s,[,w])=>s+w,0)||1;
  let mw=0; const m=[]; for (const [s,w] of rk) if (contains(x,s)){ m.push(s); mw+=w; }
  return {score:Math.min(1,mw/sat), matched:m}; }
function salaryScore(sal){ const t=PROFILE.salary.target_min, f=PROFILE.salary.soft_floor;
  if(!sal||(!sal.from&&!sal.to)) return 0.6; const top=sal.to||sal.from;
  return top>=t?1.0:(top>=f?0.7:0.2); }
function industryScore(x){ const h=Object.entries(PROFILE.industries).filter(([n])=>contains(x,n)).map(([,w])=>w);
  return h.length?Math.min(1,Math.max(...h)):0.5; }
function redFlags(t,x){ const f=[]; for(const w of PROFILE.stop_words){ if(contains(t,w))f.push('t:'+w); else if(contains(x,w))f.push(w);} return [...new Set(f)].slice(0,6); }
function scoreVac(title, desc, salary){
  const tN=norm(title), xN=norm(title+'. '+(desc||''));
  const t=titleScore(tN), s=skillsScore(xN), sal=salaryScore(salary), ind=industryScore(xN);
  const flags=redFlags(tN,xN), w=PROFILE.scoring_weights;
  let raw=t.score*w.title+s.score*w.skills+sal*w.salary+ind*w.industry;
  const pen=flags.reduce((p,f)=>p+(f.startsWith('t:')?0.12:0.06),0);
  const score=Math.round(Math.max(0,Math.min(1,raw-pen))*100);
  return {score, best_role:t.role, matched:s.matched.slice(0,6)};
}
function fromHH(v){ const sn=v.snippet||{}; return {
  id: v.id?'hh-'+v.id:'', title:v.name||v.title||'', company:(v.employer||{}).name||v.company||'',
  url:v.alternate_url||v.url||'', area:(v.area||{}).name||v.area||'', salary:v.salary||null,
  description:[sn.requirement, sn.responsibility, v.description].filter(Boolean).join(' ') }; }
function fmtSal(s){ if(!s||(!s.from&&!s.to))return 'з/п не указана';
  const c=(s.currency||'RUR').replace('RUR','руб'); const f=n=>String(n).replace(/\B(?=(\d{3})+(?!\d))/g,' ');
  if(s.from&&s.to)return f(s.from)+'–'+f(s.to)+' '+c; return (s.from?'от '+f(s.from):'до '+f(s.to))+' '+c; }

const vacs=[];
for (const it of $input.all()){ const j=it.json||{};
  if (Array.isArray(j.items)) j.items.forEach(v=>vacs.push(v)); else vacs.push(j); }
const seen=new Set(); const scored=[];
for (const v of vacs){ const m=fromHH(v); const r=scoreVac(m.title,m.description,m.salary);
  if (r.score>=PROFILE.thresholds.digest && !seen.has(m.id)){ seen.add(m.id); scored.push({...m,...r}); } }
scored.sort((a,b)=>b.score-a.score);
const top=scored.slice(0,15);
const today=new Date().toLocaleDateString('ru-RU');
let L=['🗞 Вакансии на '+today+' — '+top.length+' релевантных',''];
for (const v of top){
  L.push(v.score+'/100 · '+v.title);
  L.push('🏢 '+(v.company||'—')+' · 📍 '+(v.area||'—')+' · 💰 '+fmtSal(v.salary));
  L.push('🎯 '+v.best_role+' · ✓ '+(v.matched||[]).join(', '));
  L.push('🔗 '+(v.url||'')); L.push('');
}
const digest = top.length ? L.join('\n') : 'Сегодня релевантных вакансий не найдено.';
return [{ json: { digest, count: top.length } }];
'''


def nid():
    return str(uuid.uuid4())


def node(name, ntype, ver, params, pos, creds=None):
    n = {"id": nid(), "name": name, "type": ntype, "typeVersion": ver,
         "position": pos, "parameters": params}
    if creds:
        n["credentials"] = creds
    return n


def build():
    js = SCORE_JS.replace("__PROFILE__", PJSON)
    n_manual = node("Manual Trigger", "n8n-nodes-base.manualTrigger", 1, {}, [-700, 80])
    n_sched = node("Schedule 09:00", "n8n-nodes-base.scheduleTrigger", 1.2,
                   {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
                   [-700, 260])
    n_today = node("today", "n8n-nodes-base.code", 2,
                   {"jsCode": "const d=new Date();\nreturn [{json:{date:d.toISOString().slice(0,10)}}];"},
                   [-480, 170])
    n_token = node("HH token", "n8n-nodes-base.httpRequest", 4.2,
                   {"method": "POST", "url": "=https://api.hh.ru/token",
                    "sendHeaders": True, "headerParameters": HH_HEADERS,
                    "sendBody": True, "contentType": "form-urlencoded",
                    "bodyParameters": {"parameters": [
                        {"name": "grant_type", "value": "client_credentials"},
                        {"name": "client_id", "value": HH_CLIENT_ID},
                        {"name": "client_secret", "value": HH_CLIENT_SECRET}]},
                    "options": {}}, [-480, 30])
    # Авторизация поиска: статический токен (если задан) либо из ноды «HH token».
    if HH_STATIC_TOKEN:
        auth = {"name": "Authorization", "value": "Bearer " + HH_STATIC_TOKEN}
    else:
        auth = {"name": "Authorization", "value": "=Bearer {{ $('HH token').item.json.access_token }}"}
    search_headers = {"parameters": _BASE_HEADERS + [auth]}
    n_hh1 = node("HH Коммерческий директор", "n8n-nodes-base.httpRequest", 4.2,
                 {"url": "=https://api.hh.ru/vacancies", "sendQuery": True, "specifyQuery": "json",
                  "jsonQuery": HH_QUERY % {"role": "Коммерческий директор"},
                  "sendHeaders": True, "headerParameters": search_headers,
                  "options": {}}, [-260, 80])
    n_hh2 = node("HH Директор по маркетингу", "n8n-nodes-base.httpRequest", 4.2,
                 {"url": "=https://api.hh.ru/vacancies", "sendQuery": True, "specifyQuery": "json",
                  "jsonQuery": HH_QUERY % {"role": "директор по маркетингу"},
                  "sendHeaders": True, "headerParameters": search_headers,
                  "options": {}}, [-260, 280])
    # устойчивость к перемежающемуся 403 HH: ретраи + не ронять воркфлоу, если ветка не прошла
    for h in (n_hh1, n_hh2):
        h["retryOnFail"] = True
        h["maxTries"] = 5
        h["waitBetweenTries"] = 5000
        h["onError"] = "continueRegularOutput"
    n_merge = node("Merge", "n8n-nodes-base.merge", 3, {"mode": "append", "numberInputs": 2}, [0, 180])
    n_score = node("findwork: скоринг + дайджест", "n8n-nodes-base.code", 2, {"jsCode": js}, [240, 180])
    n_tg = node("Telegram: дайджест", "n8n-nodes-base.telegram", 1.2,
                {"chatId": "=" + CHAT_ID, "text": "={{ $json.digest }}",
                 "additionalFields": {"appendAttribution": False}},
                [480, 180], creds={"telegramApi": TELEGRAM_CRED})

    nodes = [n_manual, n_sched, n_today, n_hh1, n_hh2, n_merge, n_score, n_tg]
    if not HH_STATIC_TOKEN:
        nodes.insert(3, n_token)  # минтим токен в воркфлоу

    def conn(a, b, idx=0):
        return {a["name"]: {"main": [[{"node": b["name"], "type": "main", "index": idx}]]}}

    connections = {}

    def add(a, b, out_idx=0, in_idx=0):
        connections.setdefault(a["name"], {}).setdefault("main", [])
        m = connections[a["name"]]["main"]
        while len(m) <= out_idx:
            m.append([])
        m[out_idx].append({"node": b["name"], "type": "main", "index": in_idx})

    add(n_manual, n_today)
    add(n_sched, n_today)
    if HH_STATIC_TOKEN:
        add(n_today, n_hh1)
        add(n_today, n_hh2)
    else:
        add(n_today, n_token)
        add(n_token, n_hh1)
        add(n_token, n_hh2)
    add(n_hh1, n_merge, in_idx=0)
    add(n_hh2, n_merge, in_idx=1)
    add(n_merge, n_score)
    add(n_score, n_tg)

    return {
        "name": "hh.ru — findwork (скоринг)",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "timezone": "Europe/Moscow"},
    }


def main():
    if not N8N_KEY:
        sys.exit("Задай N8N_KEY (и опц. N8N_URL).")
    wf = build()
    data = json.dumps(wf).encode("utf-8")
    wf_id = os.environ.get("N8N_WF_ID")  # если задан — обновляем существующий (PUT)
    if wf_id:
        url, method, verb = f"{N8N_URL}/api/v1/workflows/{wf_id}", "PUT", "ОБНОВЛЁН"
    else:
        url, method, verb = f"{N8N_URL}/api/v1/workflows", "POST", "СОЗДАН"
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            out = json.loads(resp.read().decode())
        print(f"{verb} воркфлоу:")
        print("  id:", out.get("id"), "| name:", out.get("name"), "| active:", out.get("active"))
        print(f"  открой: {N8N_URL}/workflow/{out.get('id')}")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:800])
        sys.exit(1)


if __name__ == "__main__":
    main()
