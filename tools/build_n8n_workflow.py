#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создаёт/обновляет в n8n воркфлоу HH-дайджеста (оригинал не трогаем).

Поток:
  Schedule(09:00)/Manual → today → HH token (минт, не падает при лимите)
    → HH token (cache) [staticData + сид-фолбэк]
    → HH «Коммерческий директор» / «Директор по маркетингу» (Bearer; salary>=450k ИЛИ без вилки)
    → Merge → score+dedup (LIST, скоринг по сниппету, дедуп в staticData)
    → get full vacancy (/vacancies/{id}) → LLM «почему подходит» (OpenAI)
    → build digest (пересчёт скоринга по полному описанию + причина) → Telegram

Устойчивость: токен кэшируется; дедуп по id; все «обогащающие» узлы — onError continue.

Запуск:
  N8N_URL=... N8N_KEY=... HH_CLIENT_ID=... HH_CLIENT_SECRET=... HH_STATIC_TOKEN=<seed> \
  [N8N_WF_ID=<id>] [N8N_ACTIVATE=1] python3 tools/build_n8n_workflow.py
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
OPENAI_CRED = {"id": "uXn6hZoeLAiQJHNZ", "name": "Chekanal"}
CHAT_ID = "109790719"
SALARY_MIN = 450000
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")
HH_CLIENT_ID = os.environ.get("HH_CLIENT_ID", "")
HH_CLIENT_SECRET = os.environ.get("HH_CLIENT_SECRET", "")
HH_SEED_TOKEN = os.environ.get("HH_STATIC_TOKEN", "")

_BASE_HEADERS = [
    {"name": "User-Agent", "value": BROWSER_UA},
    {"name": "HH-User-Agent", "value": "findwork/1.0 (sunpavel@mail.ru)"},
    {"name": "Accept", "value": "application/json, text/plain, */*"},
    {"name": "Accept-Language", "value": "ru-RU,ru;q=0.9"},
]
HH_HEADERS = {"parameters": _BASE_HEADERS}
TOKEN_EXPR = "{{ $('HH token (cache)').first().json.access_token }}"
SEARCH_HEADERS = {"parameters": _BASE_HEADERS + [
    {"name": "Authorization", "value": "=Bearer " + TOKEN_EXPR}]}

# salary>=450000 + only_with_salary=false → вакансии от 450к ИЛИ без указанной вилки (док HH)
HH_QUERY = """={
  "text": "%(role)s",
  "only_with_salary": "false",
  "salary": %(sal)d,
  "search_field": ["name"],
  "area": 1,
  "date_from": "{{ $('today').item.json.date }}T00:00:00",
  "order_by": "publication_time",
  "page": 0,
  "per_page": 100
}"""

PICK_JS = """
const store = $getWorkflowStaticData('global');
const j = ($input.first() && $input.first().json) || {};
if (j && j.access_token) { store.hh_token = j.access_token; store.hh_token_at = Date.now(); }
return [{ json: { access_token: store.hh_token || '__SEED__' } }];
""".replace("__SEED__", HH_SEED_TOKEN)

# Общие функции скоринга (вставляются и в list-, и в build-ноду)
SCORE_FUNCS = r'''
const PROFILE = __PROFILE__;
function norm(s){ return (s||'').toString().toLowerCase().replace(/ё/g,'е').replace(/\s+/g,' '); }
function esc(s){ return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'); }
function contains(h,n){ n=norm(n);
  if(n.length<=4 && /^[\x00-\x7F]+$/.test(n)) return new RegExp('(?<![a-z])'+esc(n)+'(?![a-z])').test(h);
  return h.indexOf(n)!==-1; }
function ranked(){ return Object.entries(PROFILE.skills).sort((a,b)=>b[1]-a[1]); }
function titleScore(t){ let b=0,role='—'; for(const r of PROFILE.target_roles)
  if(r.title_keywords.some(k=>contains(t,k))&&r.weight>b){b=r.weight;role=r.name;} return {score:b,role}; }
function skillsScore(x){ const rk=ranked(); const sat=rk.slice(0,12).reduce((s,[,w])=>s+w,0)||1;
  let mw=0; const m=[]; for(const [s,w] of rk) if(contains(x,s)){m.push(s);mw+=w;}
  return {score:Math.min(1,mw/sat),matched:m}; }
function salaryScore(s){ const t=PROFILE.salary.target_min,f=PROFILE.salary.soft_floor;
  if(!s||(!s.from&&!s.to))return 0.6; const top=s.to||s.from; return top>=t?1.0:(top>=f?0.7:0.2); }
function industryScore(x){ const h=Object.entries(PROFILE.industries).filter(([n])=>contains(x,n)).map(([,w])=>w);
  return h.length?Math.min(1,Math.max(...h)):0.5; }
function redFlags(t,x){ const f=[]; for(const w of PROFILE.stop_words){ if(contains(t,w))f.push('t:'+w); else if(contains(x,w))f.push(w);} return [...new Set(f)].slice(0,6); }
function scoreVac(title,desc,salary){ const tN=norm(title),xN=norm(title+'. '+(desc||''));
  const t=titleScore(tN),s=skillsScore(xN),sal=salaryScore(salary),ind=industryScore(xN);
  const fl=redFlags(tN,xN),w=PROFILE.scoring_weights;
  let raw=t.score*w.title+s.score*w.skills+sal*w.salary+ind*w.industry;
  const pen=fl.reduce((p,f)=>p+(f.startsWith('t:')?0.12:0.06),0);
  return {score:Math.round(Math.max(0,Math.min(1,raw-pen))*100),best_role:t.role,matched:s.matched.slice(0,6)}; }
function fromHH(v){ const sn=v.snippet||{}; return {
  id:v.id?'hh-'+v.id:'', title:v.name||v.title||'', company:(v.employer||{}).name||v.company||'',
  url:v.alternate_url||v.url||'', area:(v.area||{}).name||v.area||'', salary:v.salary||null,
  description:[sn.requirement,sn.responsibility,v.description].filter(Boolean).join(' ') }; }
function strip(h){ return (h||'').replace(/<[^>]+>/g,' ').replace(/&[a-z]+;/g,' ').replace(/\s+/g,' ').trim(); }
function fmtSal(s){ if(!s||(!s.from&&!s.to))return 'з/п не указана';
  const c=(s.currency||'RUR').replace('RUR','руб'); const f=n=>String(n).replace(/\B(?=(\d{3})+(?!\d))/g,' ');
  if(s.from&&s.to)return f(s.from)+'–'+f(s.to)+' '+c; return (s.from?'от '+f(s.from):'до '+f(s.to))+' '+c; }
'''

LIST_GLUE = r'''
const store=$getWorkflowStaticData('global');
const sent=new Set(store.sent_ids||[]);
const vacs=[]; for(const it of $input.all()){const j=it.json||{}; if(Array.isArray(j.items))j.items.forEach(v=>vacs.push(v)); else vacs.push(j);}
const uniq=new Set(); const scored=[];
for(const v of vacs){const m=fromHH(v); const r=scoreVac(m.title,m.description,m.salary);
  if(r.score>=PROFILE.thresholds.digest && v.id && !uniq.has(m.id)){uniq.add(m.id);
    scored.push({hh_id:String(v.id), snippet_score:r.score, ...m});}}
scored.sort((a,b)=>b.snippet_score-a.snippet_score);
const fresh=scored.filter(v=>!sent.has(v.id)).slice(0,12);   // ограничим объём LLM/запросов
for(const v of fresh) sent.add(v.id);
store.sent_ids=Array.from(sent).slice(-8000);
return fresh.map(v=>({json:v}));
'''

BUILD_GLUE = r'''
const fulls=$('get full vacancy').all();
let llms=[]; try{ llms=$('LLM почему подходит').all(); }catch(e){}
const rows=[];
for(let i=0;i<fulls.length;i++){
  const v=(fulls[i]&&fulls[i].json)||{};
  if(!v.name) continue;
  const ks=(v.key_skills||[]).map(k=>k.name||k).join(', ');
  const desc=strip(v.description)+' '+ks;
  const r=scoreVac(v.name, desc, v.salary);
  let reason=''; try{ const lj=(llms[i]&&llms[i].json)||{}; reason=strip((lj.message&&lj.message.content)||lj.text||lj.content||''); }catch(e){}
  rows.push({score:r.score, best_role:r.best_role, matched:r.matched, name:v.name,
    company:(v.employer||{}).name||'', area:(v.area||{}).name||'', salary:v.salary,
    url:v.alternate_url||('https://hh.ru/vacancy/'+v.id), reason});
}
rows.sort((a,b)=>b.score-a.score);
if(rows.length===0) return [];
const today=new Date().toLocaleDateString('ru-RU');
let L=['🗞 Вакансии на '+today+' — '+rows.length+' новых релевантных',''];
for(const v of rows){
  L.push(v.score+'/100 · '+v.name);
  L.push('🏢 '+(v.company||'—')+' · 📍 '+(v.area||'—')+' · 💰 '+fmtSal(v.salary));
  if(v.reason) L.push('💡 '+v.reason);
  else L.push('🎯 '+v.best_role+' · ✓ '+(v.matched||[]).join(', '));
  L.push('🔗 '+(v.url||'')); L.push('');
}
return [{ json: { digest: L.join('\n'), count: rows.length } }];
'''

LLM_PROMPT = ("=Ты — HR-эксперт по подбору топ-менеджеров. В 1–2 предложениях (до 280 символов, "
              "по-русски, без префиксов и без JSON) объясни, почему эта вакансия подходит кандидату "
              "и на что обратить внимание.\n\n"
              "Кандидат: Коммерческий/маркетинговый директор (CMO/CCO), 16+ лет. Сильные стороны: "
              "P&L, управление продажами и маркетингом, ROMI/CAC/LTV, бренд и PR tier-1, CRM-маркетинг, "
              "запуск и масштабирование, B2B Enterprise/B2G/B2C; отрасли — IT/SaaS, девелопмент, ритейл. "
              "Доход от 450к (цель 600–900к).\n\n"
              "Вакансия:\n"
              "Название: {{ $json.name }}\n"
              "Ключевые навыки: {{ ($json.key_skills || []).map(k => k.name).join(', ') }}\n"
              "Описание: {{ ($json.description || '').replace(/<[^>]+>/g,' ').slice(0, 1500) }}")


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
    cont = {"onError": "continueRegularOutput"}
    n_manual = node("Manual Trigger", "n8n-nodes-base.manualTrigger", 1, {}, [-1000, 80])
    n_sched = node("Schedule 09:00", "n8n-nodes-base.scheduleTrigger", 1.2,
                   {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
                   [-1000, 260])
    n_today = node("today", "n8n-nodes-base.code", 2,
                   {"jsCode": "return [{json:{date:new Date().toISOString().slice(0,10)}}];"}, [-800, 170])
    n_mint = node("HH token", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": "=https://api.hh.ru/token",
                   "sendHeaders": True, "headerParameters": HH_HEADERS,
                   "sendBody": True, "contentType": "form-urlencoded",
                   "bodyParameters": {"parameters": [
                       {"name": "grant_type", "value": "client_credentials"},
                       {"name": "client_id", "value": HH_CLIENT_ID},
                       {"name": "client_secret", "value": HH_CLIENT_SECRET}]},
                   "options": {}}, [-620, 60], extra=cont)
    n_pick = node("HH token (cache)", "n8n-nodes-base.code", 2, {"jsCode": PICK_JS}, [-620, 250])
    n_hh1 = node("HH Коммерческий директор", "n8n-nodes-base.httpRequest", 4.2,
                 {"url": "=https://api.hh.ru/vacancies", "sendQuery": True, "specifyQuery": "json",
                  "jsonQuery": HH_QUERY % {"role": "Коммерческий директор", "sal": SALARY_MIN},
                  "sendHeaders": True, "headerParameters": SEARCH_HEADERS, "options": {}},
                 [-420, 160], extra={"onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 4000})
    n_hh2 = node("HH Директор по маркетингу", "n8n-nodes-base.httpRequest", 4.2,
                 {"url": "=https://api.hh.ru/vacancies", "sendQuery": True, "specifyQuery": "json",
                  "jsonQuery": HH_QUERY % {"role": "директор по маркетингу", "sal": SALARY_MIN},
                  "sendHeaders": True, "headerParameters": SEARCH_HEADERS, "options": {}},
                 [-420, 360], extra={"onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 4000})
    n_merge = node("Merge", "n8n-nodes-base.merge", 3, {"mode": "append", "numberInputs": 2}, [-220, 260])
    n_list = node("score+dedup", "n8n-nodes-base.code", 2,
                  {"jsCode": (SCORE_FUNCS + LIST_GLUE).replace("__PROFILE__", PJSON)}, [-20, 260])
    n_getvac = node("get full vacancy", "n8n-nodes-base.httpRequest", 4.2,
                    {"url": "=https://api.hh.ru/vacancies/{{ $json.hh_id }}",
                     "sendHeaders": True, "headerParameters": SEARCH_HEADERS, "options": {}},
                    [180, 260], extra={"onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 2, "waitBetweenTries": 3000})
    n_llm = node("LLM почему подходит", "@n8n/n8n-nodes-langchain.openAi", 1.8,
                 {"modelId": {"__rl": True, "value": "gpt-4.1-nano", "mode": "list",
                              "cachedResultName": "GPT-4.1-NANO"},
                  "messages": {"values": [{"content": LLM_PROMPT}]}, "options": {}},
                 [380, 260], creds={"openAiApi": OPENAI_CRED}, extra=cont)
    n_build = node("build digest", "n8n-nodes-base.code", 2,
                   {"jsCode": (SCORE_FUNCS + BUILD_GLUE).replace("__PROFILE__", PJSON)}, [580, 260])
    n_tg = node("Telegram: дайджест", "n8n-nodes-base.telegram", 1.2,
                {"chatId": "=" + CHAT_ID, "text": "={{ $json.digest }}",
                 "additionalFields": {"appendAttribution": False}},
                [780, 260], creds={"telegramApi": TELEGRAM_CRED})

    nodes = [n_manual, n_sched, n_today, n_mint, n_pick, n_hh1, n_hh2, n_merge,
             n_list, n_getvac, n_llm, n_build, n_tg]
    connections = {}

    def add(a, b, in_idx=0):
        m = connections.setdefault(a["name"], {}).setdefault("main", [])
        while len(m) <= 0:
            m.append([])
        m[0].append({"node": b["name"], "type": "main", "index": in_idx})

    add(n_manual, n_today)
    add(n_sched, n_today)
    add(n_today, n_mint)
    add(n_mint, n_pick)
    add(n_pick, n_hh1)
    add(n_pick, n_hh2)
    connections.setdefault("HH Коммерческий директор", {}).setdefault("main", [[]])[0].append(
        {"node": "Merge", "type": "main", "index": 0})
    connections.setdefault("HH Директор по маркетингу", {}).setdefault("main", [[]])[0].append(
        {"node": "Merge", "type": "main", "index": 1})
    add(n_merge, n_list)
    add(n_list, n_getvac)
    add(n_getvac, n_llm)
    add(n_llm, n_build)
    add(n_build, n_tg)

    return {"name": "hh.ru — findwork (скоринг)", "nodes": nodes, "connections": connections,
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
        print(f"открой: {N8N_URL}/workflow/{wf_id}")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:800]); sys.exit(1)


if __name__ == "__main__":
    main()
