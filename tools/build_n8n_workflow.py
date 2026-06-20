#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Создаёт/обновляет в n8n воркфлоу HH-дайджеста (оригинал не трогаем).

Поток:
  Schedule(каждые 2ч 9-21)/Manual → today → HH token (минт, не падает при лимите)
    → HH token (cache) [staticData + сид-фолбэк]
    → HH мои отклики (/negotiations; личный токен → исключаем уже-откликнутые; app-токен → 403/skip)
    → HH «Коммерческий директор» / «Директор по маркетингу» (Bearer; salary>=450k ИЛИ без вилки)
    → Merge → score+dedup (LIST, скоринг по сниппету, дедуп + минус уже-откликнутые, staticData)
    → get full vacancy (/vacancies/{id}) → LLM-судья по мастер-резюме (OpenAI gpt-4o, JSON fit)
    → build digest (ранжирование по fit судьи; keyword — фолбэк + пре-фильтр) → Telegram

Параллельные ветки от «today»:
  • facancy.ru: API /api/v1/vacancies → фильтр 450к → скоринг → LLM → Telegram (👍/👎).
  • Telegram-каналы: t.me/s/<канал> (DEFAULT_TG_CHANNELS) → отбор вакансий → скоринг → LLM → Telegram.

Устойчивость: токен кэшируется; дедуп по id; все «обогащающие» узлы — onError continue.

Вебхук приёма откликов от бота: POST /webhook/findwork-applied {"applied_ids":[...]} →
staticData (score+dedup исключает их). Опц. секрет N8N_APPLIED_TOKEN (заголовок X-Findwork-Token).

Запуск:
  N8N_URL=... N8N_KEY=... HH_CLIENT_ID=... HH_CLIENT_SECRET=... HH_STATIC_TOKEN=<seed> \
  [N8N_APPLIED_TOKEN=<секрет>] [N8N_WF_ID=<id>] [N8N_ACTIVATE=1] python3 tools/build_n8n_workflow.py
"""
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "profile" / "profile.json").read_text(encoding="utf-8"))
PJSON = json.dumps(PROFILE, ensure_ascii=False)

# Список Telegram-каналов — из единого источника (src/sources.DEFAULT_TG_CHANNELS).
sys.path.insert(0, str(ROOT / "src"))
try:
    from sources import DEFAULT_TG_CHANNELS as TG_CHANNELS  # noqa: E402
except Exception:  # noqa: BLE001 — фолбэк, если импорт недоступен
    TG_CHANNELS = ["vacanciesrus", "finexecutive", "theypaywell", "marketing_jobs",
                   "perezvonyu", "prwork", "morejobs"]

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
// Уже откликнутые на hh.ru (история /negotiations). Требует ЛИЧНОГО токена HH; на app-токене
// узел «HH мои отклики» отдаёт 403 (onError continue) → applied останется прежним и фильтр
// просто не применится. Запоминаем в staticData, чтобы разовый сбой не вернул откликнутые.
let applied=new Set(store.applied_ids||[]);
try{ for(const it of $('HH мои отклики').all()){ const j=(it&&it.json)||{};
  const arr=Array.isArray(j.items)?j.items:(j&&j.id?[j]:[]);
  for(const n of arr){ const vid=(n&&n.vacancy&&n.vacancy.id)||(n&&n.vacancy_id);
    if(vid) applied.add('hh-'+String(vid)); } } }catch(e){}
store.applied_ids=Array.from(applied).slice(-8000);
const vacs=[]; for(const it of $input.all()){const j=it.json||{}; if(Array.isArray(j.items))j.items.forEach(v=>vacs.push(v)); else vacs.push(j);}
const uniq=new Set(); const scored=[];
for(const v of vacs){const m=fromHH(v); const r=scoreVac(m.title,m.description,m.salary);
  if(r.score>=PROFILE.thresholds.skip_below && v.id && !uniq.has(m.id) && !applied.has(m.id)){uniq.add(m.id);
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
function parseJudge(txt){ if(!txt) return null; const s=String(txt); const a=s.indexOf('{'), b=s.lastIndexOf('}'); if(a<0||b<0||b<a) return null; try{ return JSON.parse(s.slice(a,b+1)); }catch(e){ return null; } }
function ago(iso){ if(!iso) return ''; const d=new Date(iso); if(isNaN(d.getTime())) return ''; const h=Math.floor((Date.now()-d.getTime())/3600000); if(h<1) return 'только что'; if(h<24) return h+'ч назад'; return Math.floor(h/24)+'д назад'; }
const MIN=PROFILE.thresholds.digest;
const rows=[];
for(let i=0;i<fulls.length;i++){
  const v=(fulls[i]&&fulls[i].json)||{};
  if(!v.name) continue;
  const ks=(v.key_skills||[]).map(k=>k.name||k).join(', ');
  const desc=strip(v.description)+' '+ks;
  const kw=scoreVac(v.name, desc, v.salary);   // keyword — фолбэк, если судья недоступен
  let raw=''; try{ const lj=(llms[i]&&llms[i].json)||{}; raw=(lj.message&&lj.message.content)||lj.text||lj.content||''; }catch(e){}
  const j=parseJudge(raw);
  const score=(j&&isFinite(+j.fit_score))?Math.round(+j.fit_score):kw.score;
  const why=(j&&j.why)?strip(j.why):'';
  const gaps=(j&&Array.isArray(j.gaps))?j.gaps.slice(0,2):[];
  const level=(j&&j.level_match)?String(j.level_match):'';
  if(score<MIN) continue;
  rows.push({score, why, gaps, level, best_role:kw.best_role, matched:kw.matched, name:v.name,
    company:(v.employer||{}).name||'', area:(v.area||{}).name||'', salary:v.salary,
    published:v.published_at||'', hh_id:String(v.id||''), url:v.alternate_url||('https://hh.ru/vacancy/'+v.id)});
}
rows.sort((a,b)=>b.score-a.score);
if(rows.length===0) return [];
// одна карточка = одно сообщение; кнопки (Отклик/👍/👎) вешает Telegram-нода по hhid/id
return rows.map(v=>{
  let b=v.score+'/100 · '+v.name+'\n';
  b+='🏢 '+(v.company||'—')+' · 📍 '+(v.area||'—')+' · 💰 '+fmtSal(v.salary)+'\n';
  if(v.why) b+='💡 '+v.why.slice(0,240)+'\n';
  else b+='🎯 '+v.best_role+' · ✓ '+(v.matched||[]).join(', ')+'\n';
  if(v.gaps&&v.gaps.length) b+='⚠️ '+v.gaps.join('; ').slice(0,200)+'\n';
  const fr=ago(v.published); const lv=(v.level&&v.level!=='в уровень')?('📊 '+v.level):'';
  const meta=[fr?('🕐 '+fr):'', lv].filter(Boolean).join(' · ');
  if(meta) b+=meta+'\n';
  b+='🔗 '+(v.url||'');
  return { json: { text:b, hhid:v.hh_id, id:'hh-'+v.hh_id } };
});
'''

# Карточка экспертизы — выжимка из resume/master_cco.md (источник правды о реальном опыте).
EXPERTISE_CARD = (
    "Скворцов Павел, коммерческий/маркетинговый директор (CCO/CMO), 16+ лет. Логика P&L, ROMI, CAC/LTV. Реальный опыт:\n"
    "- CCO федеральной сети TERMOLAND (B2C): рост с 3 до 14 объектов, +40% чек, +50% поток, медиабюджет >5 млн/мес, подписная модель, CRM-воронка, AI-инструменты.\n"
    "- CCO IT-стартапа Rukki.pro (B2B): отдел продаж с нуля, x8 доходности за 3 мес, контракты с Топ-5 застройщиков, резидент Skolkovo.\n"
    "- CMO Pragmacore (ERP, B2B Enterprise/B2G): вывод продукта в Топ-5 рынка, план выручки 150 млн, PR в РБК/Forbes/Ведомости.\n"
    "- Руководитель маркетинга в девелопменте (ASTERUS, Главстрой, НДВ): отделы с нуля, performance, бренд, снижение CPL.\n"
    "Силён: коммерческий блок (продажи+маркетинг+продукт), стратегия и бюджетирование, построение отделов с нуля, "
    "ROMI/CAC/LTV/CPL, CRM-маркетинг/retention/подписки, бренд и PR tier-1, AI-инструменты. "
    "Отрасли: IT/SaaS, девелопмент/недвижимость, ритейл, услуги. Рынки B2B Enterprise/B2G/B2C.\n"
    "Уровень: директор функции / C-level. Английский B1. Москва, не готов к переезду (командировки ок). "
    "Доход: цель 600-900к, мягкий пол 450к."
)

# LLM-судья: оценивает попадание вакансии под реальный опыт и УРОВЕНЬ (не по словам), возвращает JSON.
LLM_PROMPT = (
    "=Ты — придирчивый карьерный эксперт уровня Executive Search. Оцени, насколько вакансия подходит "
    "КОНКРЕТНОМУ кандидату по его реальному опыту и УРОВНЮ, а не по совпадению слов.\n\n"
    "КАНДИДАТ (источник правды о его опыте):\n" + EXPERTISE_CARD + "\n\n"
    "КРИТЕРИИ (думай по сути):\n"
    "1. Функция: коммерция / маркетинг / рост — его поле.\n"
    "2. УРОВЕНЬ: целевая полка — ДИРЕКТОР ФУНКЦИИ / C-level (CCO, CMO, директор по развитию/продажам, "
    "глава направления, вице-президент) = «в уровень». Руководитель группы, тимлид, старший/рядовой "
    "менеджер, специалист, координатор = «ниже» = низкий балл. Первое лицо крупной корпорации = «выше» = риск.\n"
    "3. Отрасль: IT/SaaS, девелопмент/недвижимость, ритейл, услуги — близко (но отрасль не вето).\n"
    "4. Требования: что он реально закрывает опытом, чего не хватает.\n"
    "5. Красные флаги: продажи «в полях», пустой титул, агентство/массовый найм, переезд (не готов), "
    "узкая нерелевантная специфика.\n\n"
    "Верни СТРОГО валидный JSON (без markdown, без пояснений вне JSON):\n"
    '{"fit_score":0-100,"level_match":"ниже|в уровень|выше","why":"1-2 предложения, почему релевантно '
    'ИМЕННО его опыту, с конкретикой","gaps":["чего не хватает / на что смотреть"],'
    '"risks":["красные флаги — может быть пусто"]}\n'
    "fit_score: 80+ сильное попадание в его профиль; 55-79 релевантно; <55 слабо. Понижение по уровню = ниже 55.\n\n"
    "ВАКАНСИЯ:\n"
    "Название: {{ $json.name }}\n"
    "Ключевые навыки: {{ ($json.key_skills || []).map(k => (k && k.name) || k).join(', ') }}\n"
    "Описание: {{ ($json.description || '').toString().replace(/<[^>]+>/g,' ').slice(0, 1800) }}")

# facancy.ru: сбор по API (/api/v1/vacancies?page=N) + фильтр 450к/без вилки + скоринг + дедуп
FAC_FETCH_GLUE = r'''
const UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const PAGES=12; let all=[];
for(let p=1;p<=PAGES;p++){
  let resp; try{ resp=await this.helpers.httpRequest({url:'https://facancy.ru/api/v1/vacancies?page='+p,
    headers:{'User-Agent':UA,'Accept':'application/json'}, json:true}); }catch(e){ break; }
  const data=(resp&&resp.data)||[]; if(!data.length) break; all=all.concat(data);
}
const store=$getWorkflowStaticData('global'); const sent=new Set(store.sent_ids||[]);
const uniq=new Set(); const rel=[];
for(const v of all){
  if(v.is_outdated||v.is_removed_from_publication) continue;  // is_filled ≠ «закрыта», не фильтруем
  const be=(v.salary&&v.salary.by_employer)||null;
  const salary=be&&(be.min||be.max)?{from:be.min,to:be.max,currency:'RUR'}:null;
  const top=salary?(salary.to||salary.from):null;
  if(top!==null && top<450000) continue;                 // от 450к ИЛИ без вилки
  const id='fac-'+v.id; const desc=strip(v.text);
  const r=scoreVac(v.title, desc, salary);
  if(r.score>=PROFILE.thresholds.skip_below && !uniq.has(id)){ uniq.add(id);
    rel.push({id, source:'facancy', name:v.title, area:v.city||'', salary,
      url:'https://facancy.ru/vacancies/'+v.slug, description:desc,
      score:r.score, best_role:r.best_role, matched:r.matched}); }
}
rel.sort((a,b)=>b.score-a.score);
const fresh=rel.filter(v=>!sent.has(v.id)).slice(0,10);
for(const v of fresh) sent.add(v.id);
store.sent_ids=Array.from(sent).slice(-8000);
return fresh.map(v=>({json:v}));
'''

FAC_BUILD_GLUE = r'''
const items=$('facancy: сбор+скоринг').all();
let llms=[]; try{ llms=$('facancy: LLM').all(); }catch(e){}
function parseJudge(txt){ if(!txt) return null; const s=String(txt); const a=s.indexOf('{'), b=s.lastIndexOf('}'); if(a<0||b<0||b<a) return null; try{ return JSON.parse(s.slice(a,b+1)); }catch(e){ return null; } }
const MIN=PROFILE.thresholds.digest;
const rows=[];
for(let i=0;i<items.length;i++){ const v=items[i].json||{};
  let raw=''; try{ const lj=(llms[i]&&llms[i].json)||{}; raw=(lj.message&&lj.message.content)||lj.text||lj.content||''; }catch(e){}
  const j=parseJudge(raw);
  const score=(j&&isFinite(+j.fit_score))?Math.round(+j.fit_score):(v.score||0);
  const why=(j&&j.why)?strip(j.why):'';
  const gaps=(j&&Array.isArray(j.gaps))?j.gaps.slice(0,2):[];
  const level=(j&&j.level_match)?String(j.level_match):'';
  if(score<MIN) continue;
  rows.push(Object.assign({}, v, {score, why, gaps, level}));
}
rows.sort((a,b)=>b.score-a.score);
if(rows.length===0) return [];
return rows.map(v=>{ let b=v.score+'/100 · '+v.name+'\n';
  b+='🏢 facancy.ru · 📍 '+(v.area||'—')+' · 💰 '+fmtSal(v.salary)+'\n';
  if(v.why) b+='💡 '+v.why.slice(0,240)+'\n'; else b+='🎯 '+(v.best_role||'')+'\n';
  if(v.gaps&&v.gaps.length) b+='⚠️ '+v.gaps.join('; ').slice(0,200)+'\n';
  if(v.level&&v.level!=='в уровень') b+='📊 '+v.level+'\n';
  b+='🔗 '+(v.url||'');
  return { json: { text:b, url:v.url||'', id:v.id||'' } };
});
'''


# Telegram-каналы: публичная витрина t.me/s/<канал> (логика src/webchan.py на JS) →
# отбор «похоже на вакансию» → скоринг → дедуп. Список каналов подставляется как JSON-массив.
CHAN_FETCH_GLUE = r'''
const CHANNELS=__CHANNELS__;
const UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36';
const VAC=['ваканс','ищем','ищу','требуется','в команду','зарплат','оклад','доход','вилка','з/п','зп ','hiring','ищется','открыт набор','позиц','релокац','remote','удалённо','удаленно','оффер'];
const ROLE=['директор','руководител','head','cmo','cco','cpo','vp','вице-президент','chief','лид','lead','глава'];
function looksVac(t){ const tl=t.toLowerCase(); if(tl.length<120) return false;
  return VAC.some(w=>tl.indexOf(w)!==-1) && ROLE.some(w=>tl.indexOf(w)!==-1); }
function parsePosts(html){ const out=[]; const parts=String(html).split('data-post="');
  for(let i=1;i<parts.length;i++){ const ch=parts[i]; const mid=ch.split('"')[0];
    const m=ch.match(/tgme_widget_message_text[^>]*>([\s\S]*?)<\/div>/);
    let text=''; if(m){ text=m[1].replace(/<br\s*\/?>/g,'\n').replace(/<[^>]+>/g,' ').replace(/&[a-z]+;/g,' ').replace(/[ \t]+/g,' ').trim(); }
    const dm=ch.match(/datetime="([^"]+)"/);
    if(text) out.push({id:mid, text, url:'https://t.me/'+mid, date:dm?dm[1]:''}); }
  return out; }
const store=$getWorkflowStaticData('global');
const sent=new Set(store.sent_ids||[]); const applied=new Set(store.applied_ids||[]);
const uniq=new Set(); const rel=[];
for(const c of CHANNELS){
  let html=''; try{ html=await this.helpers.httpRequest({url:'https://t.me/s/'+c,
    headers:{'User-Agent':UA,'Accept-Language':'ru,en'}}); }catch(e){ continue; }
  for(const p of parsePosts(html)){
    if(!looksVac(p.text)) continue;
    const id='tg-'+p.id.replace(/\//g,'-');
    if(uniq.has(id)||sent.has(id)||applied.has(id)) continue; uniq.add(id);
    const title=((p.text.split('\n')[0]||p.text)).slice(0,120).trim();
    const r=scoreVac(title, p.text, null);
    if(r.score<PROFILE.thresholds.skip_below) continue;
    rel.push({id, source:'tg', name:title, company:'@'+c, area:'', salary:null,
      url:p.url, published:p.date, description:p.text.slice(0,3000),
      score:r.score, best_role:r.best_role, matched:r.matched}); }
}
rel.sort((a,b)=>b.score-a.score);
const fresh=rel.slice(0,10);
for(const v of fresh) sent.add(v.id);
store.sent_ids=Array.from(sent).slice(-8000);
return fresh.map(v=>({json:v}));
'''

CHAN_BUILD_GLUE = r'''
const items=$('tg: сбор+скоринг').all();
let llms=[]; try{ llms=$('tg: LLM').all(); }catch(e){}
function parseJudge(txt){ if(!txt) return null; const s=String(txt); const a=s.indexOf('{'), b=s.lastIndexOf('}'); if(a<0||b<0||b<a) return null; try{ return JSON.parse(s.slice(a,b+1)); }catch(e){ return null; } }
const MIN=PROFILE.thresholds.digest;
const rows=[];
for(let i=0;i<items.length;i++){ const v=items[i].json||{};
  let raw=''; try{ const lj=(llms[i]&&llms[i].json)||{}; raw=(lj.message&&lj.message.content)||lj.text||lj.content||''; }catch(e){}
  const j=parseJudge(raw);
  const score=(j&&isFinite(+j.fit_score))?Math.round(+j.fit_score):(v.score||0);
  const why=(j&&j.why)?strip(j.why):'';
  const gaps=(j&&Array.isArray(j.gaps))?j.gaps.slice(0,2):[];
  const level=(j&&j.level_match)?String(j.level_match):'';
  if(score<MIN) continue;
  rows.push(Object.assign({}, v, {score, why, gaps, level}));
}
rows.sort((a,b)=>b.score-a.score);
if(rows.length===0) return [];
return rows.map(v=>{ let b=v.score+'/100 · '+v.name+'\n';
  b+='📣 '+(v.company||'Telegram')+' · 💰 '+fmtSal(v.salary)+'\n';
  if(v.why) b+='💡 '+v.why.slice(0,240)+'\n'; else b+='🎯 '+(v.best_role||'')+'\n';
  if(v.gaps&&v.gaps.length) b+='⚠️ '+v.gaps.join('; ').slice(0,200)+'\n';
  if(v.level&&v.level!=='в уровень') b+='📊 '+v.level+'\n';
  b+='🔗 '+(v.url||'');
  return { json: { text:b, url:v.url||'', id:v.id||'' } };
});
'''


# Вебхук приёма истории откликов от бота (у бота личный токен HH). Кладёт hh-id в staticData,
# откуда их читает score+dedup. Опц. общий секрет N8N_APPLIED_TOKEN (заголовок X-Findwork-Token).
APPLIED_SYNC_JS = r'''
const store=$getWorkflowStaticData('global');
const item=($input.first()&&$input.first().json)||{};
const SECRET='__APPLIED_TOKEN__';
const hdrs=item.headers||{};
if(SECRET && (hdrs['x-findwork-token']||hdrs['X-Findwork-Token'])!==SECRET){
  return [{json:{ok:false, error:'unauthorized'}}];
}
const b=(item.body!==undefined?item.body:item)||{};
let ids=b.applied_ids||b.ids||[];
if(!Array.isArray(ids)) ids=[];
const cur=new Set(store.applied_ids||[]);
for(const x of ids){ if(x){ const s=String(x); cur.add(s.indexOf('hh-')===0?s:('hh-'+s)); } }
store.applied_ids=Array.from(cur).slice(-8000);
return [{json:{ok:true, stored:store.applied_ids.length}}];
'''


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
    n_sched = node("Scan каждые 2ч (9-21)", "n8n-nodes-base.scheduleTrigger", 1.2,
                   {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9-21/2 * * *"}]}},
                   [-1000, 260])
    n_today = node("today", "n8n-nodes-base.code", 2,
                   {"jsCode": "const d=new Date(Date.now()-3*86400000);\n"
                              "return [{json:{date:d.toISOString().slice(0,10)}}];"}, [-800, 170])
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
    # История откликов соискателя: чтобы не показывать вакансии, на которые уже откликнулся
    # (ручные на hh.ru + через бота). Нужен ЛИЧНЫЙ токен HH; на app-токене → 403 (continue).
    n_apps = node("HH мои отклики", "n8n-nodes-base.httpRequest", 4.2,
                  {"url": "=https://api.hh.ru/negotiations?per_page=100&page=0",
                   "sendHeaders": True, "headerParameters": SEARCH_HEADERS, "options": {}},
                  [-420, -40],
                  extra={"onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 2, "waitBetweenTries": 3000})
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
                 {"modelId": {"__rl": True, "value": "gpt-4o", "mode": "list",
                              "cachedResultName": "GPT-4O"},
                  "messages": {"values": [{"content": LLM_PROMPT}]}, "options": {}},
                 [380, 260], creds={"openAiApi": OPENAI_CRED}, extra=cont)
    n_build = node("build digest", "n8n-nodes-base.code", 2,
                   {"jsCode": (SCORE_FUNCS + BUILD_GLUE).replace("__PROFILE__", PJSON)}, [580, 260])
    n_tg = node("Telegram: дайджест", "n8n-nodes-base.telegram", 1.2,
                {"chatId": "=" + CHAT_ID, "text": "={{ $json.text }}",
                 "additionalFields": {"appendAttribution": False},
                 "replyMarkup": "inlineKeyboard",
                 "inlineKeyboard": {"rows": [{"row": {"buttons": [
                     {"text": "📝 Отклик", "additionalFields": {"callback_data": "=ap:{{ $json.hhid }}"}},
                     {"text": "👍", "additionalFields": {"callback_data": "=up:{{ $json.id }}"}},
                     {"text": "👎", "additionalFields": {"callback_data": "=dn:{{ $json.id }}"}}]}}]}},
                [780, 260], creds={"telegramApi": TELEGRAM_CRED},
                extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000})

    # --- независимая ветка facancy.ru ---
    n_fac = node("facancy: сбор+скоринг", "n8n-nodes-base.code", 2,
                 {"jsCode": (SCORE_FUNCS + FAC_FETCH_GLUE).replace("__PROFILE__", PJSON)},
                 [-20, 560], extra=cont)
    n_fac_llm = node("facancy: LLM", "@n8n/n8n-nodes-langchain.openAi", 1.8,
                     {"modelId": {"__rl": True, "value": "gpt-4o", "mode": "list",
                                  "cachedResultName": "GPT-4O"},
                      "messages": {"values": [{"content": LLM_PROMPT}]}, "options": {}},
                     [380, 560], creds={"openAiApi": OPENAI_CRED}, extra=cont)
    n_fac_build = node("facancy: дайджест", "n8n-nodes-base.code", 2,
                       {"jsCode": (SCORE_FUNCS + FAC_BUILD_GLUE).replace("__PROFILE__", PJSON)}, [580, 560])
    n_fac_tg = node("Telegram facancy", "n8n-nodes-base.telegram", 1.2,
                    {"chatId": "=" + CHAT_ID, "text": "={{ $json.text }}",
                     "additionalFields": {"appendAttribution": False},
                     "replyMarkup": "inlineKeyboard",
                     "inlineKeyboard": {"rows": [{"row": {"buttons": [
                         {"text": "👍", "additionalFields": {"callback_data": "=up:{{ $json.id }}"}},
                         {"text": "👎", "additionalFields": {"callback_data": "=dn:{{ $json.id }}"}}]}}]}},
                    [780, 560], creds={"telegramApi": TELEGRAM_CRED},
                    extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000})

    # --- независимая ветка Telegram-каналов (t.me/s/<канал>) ---
    n_chan = node("tg: сбор+скоринг", "n8n-nodes-base.code", 2,
                  {"jsCode": (SCORE_FUNCS + CHAN_FETCH_GLUE).replace("__PROFILE__", PJSON)
                   .replace("__CHANNELS__", json.dumps(TG_CHANNELS, ensure_ascii=False))},
                  [-20, 900], extra=cont)
    n_chan_llm = node("tg: LLM", "@n8n/n8n-nodes-langchain.openAi", 1.8,
                      {"modelId": {"__rl": True, "value": "gpt-4o", "mode": "list",
                                   "cachedResultName": "GPT-4O"},
                       "messages": {"values": [{"content": LLM_PROMPT}]}, "options": {}},
                      [380, 900], creds={"openAiApi": OPENAI_CRED}, extra=cont)
    n_chan_build = node("tg: дайджест", "n8n-nodes-base.code", 2,
                        {"jsCode": (SCORE_FUNCS + CHAN_BUILD_GLUE).replace("__PROFILE__", PJSON)}, [580, 900])
    n_chan_tg = node("Telegram tg-каналы", "n8n-nodes-base.telegram", 1.2,
                     {"chatId": "=" + CHAT_ID, "text": "={{ $json.text }}",
                      "additionalFields": {"appendAttribution": False},
                      "replyMarkup": "inlineKeyboard",
                      "inlineKeyboard": {"rows": [{"row": {"buttons": [
                          {"text": "👍", "additionalFields": {"callback_data": "=up:{{ $json.id }}"}},
                          {"text": "👎", "additionalFields": {"callback_data": "=dn:{{ $json.id }}"}}]}}]}},
                     [780, 900], creds={"telegramApi": TELEGRAM_CRED},
                     extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000})

    # Вебхук приёма откликов от бота → staticData (отдельный триггер, та же staticData воркфлоу).
    n_sync_wh = node("Webhook: applied", "n8n-nodes-base.webhook", 2,
                     {"httpMethod": "POST", "path": "findwork-applied", "responseMode": "lastNode",
                      "options": {}}, [-1000, 760], extra={"webhookId": nid()})
    n_sync_code = node("store applied", "n8n-nodes-base.code", 2,
                       {"jsCode": APPLIED_SYNC_JS.replace(
                           "__APPLIED_TOKEN__", os.environ.get("N8N_APPLIED_TOKEN", ""))},
                       [-780, 760])

    nodes = [n_manual, n_sched, n_today, n_mint, n_pick, n_apps, n_hh1, n_hh2, n_merge,
             n_list, n_getvac, n_llm, n_build, n_tg,
             n_fac, n_fac_llm, n_fac_build, n_fac_tg,
             n_chan, n_chan_llm, n_chan_build, n_chan_tg,
             n_sync_wh, n_sync_code]
    connections = {}

    def add(a, b, in_idx=0):
        m = connections.setdefault(a["name"], {}).setdefault("main", [])
        while len(m) <= 0:
            m.append([])
        m[0].append({"node": b["name"], "type": "main", "index": in_idx})

    if os.environ.get("ADD_WEBHOOK"):
        n_wh = node("Webhook test", "n8n-nodes-base.webhook", 2,
                    {"httpMethod": "GET", "path": "findwork-run-7x", "responseMode": "lastNode"},
                    [-1000, 440], extra={"webhookId": nid()})
        nodes.append(n_wh)

    add(n_manual, n_today)
    add(n_sched, n_today)
    if os.environ.get("ADD_WEBHOOK"):
        connections.setdefault("Webhook test", {}).setdefault("main", [[]])[0].append(
            {"node": "today", "type": "main", "index": 0})
    add(n_today, n_mint)
    add(n_mint, n_pick)
    # token cache → история откликов → оба HH-поиска (гарантируем, что отклики получены до score+dedup)
    add(n_pick, n_apps)
    add(n_apps, n_hh1)
    add(n_apps, n_hh2)
    connections.setdefault("HH Коммерческий директор", {}).setdefault("main", [[]])[0].append(
        {"node": "Merge", "type": "main", "index": 0})
    connections.setdefault("HH Директор по маркетингу", {}).setdefault("main", [[]])[0].append(
        {"node": "Merge", "type": "main", "index": 1})
    add(n_merge, n_list)
    add(n_list, n_getvac)
    add(n_getvac, n_llm)
    add(n_llm, n_build)
    add(n_build, n_tg)
    # facancy-ветка (параллельно HH)
    add(n_today, n_fac)
    add(n_fac, n_fac_llm)
    add(n_fac_llm, n_fac_build)
    add(n_fac_build, n_fac_tg)
    # ветка Telegram-каналов (параллельно HH/facancy)
    add(n_today, n_chan)
    add(n_chan, n_chan_llm)
    add(n_chan_llm, n_chan_build)
    add(n_chan_build, n_chan_tg)
    # ветка приёма откликов от бота (независимый триггер)
    add(n_sync_wh, n_sync_code)

    return {"name": "hh.ru — findwork (скоринг)", "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1", "timezone": "Europe/Moscow"}}


def _api(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{N8N_URL}/api/v1{path}", data=data, method=method,
                                 headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode())


def _find_wf_id_by_name(name):
    """id существующего воркфлоу по имени (чтобы обновлять его, а не плодить дубликаты)."""
    try:
        out = _api("/workflows")
    except Exception:  # noqa: BLE001
        return None
    items = out.get("data") if isinstance(out, dict) else (out if isinstance(out, list) else [])
    for w in items or []:
        if w.get("name") == name:
            return w.get("id")
    return None


WF_NAME = "hh.ru — findwork (скоринг)"


def _existing_hh_creds(wf_id):
    """HH client_id/secret (и сид-токен) из узлов уже существующего воркфлоу — чтобы не
    вводить их заново при каждом перевыпуске. {} — если воркфлоу/узлов нет."""
    out = {}
    if not wf_id:
        return out
    try:
        wf = _api(f"/workflows/{wf_id}")
    except Exception:  # noqa: BLE001
        return out
    for n in wf.get("nodes", []) or []:
        params = n.get("parameters") or {}
        if n.get("name") == "HH token":
            for p in ((params.get("bodyParameters") or {}).get("parameters") or []):
                if p.get("name") in ("client_id", "client_secret") and p.get("value"):
                    out[p["name"]] = p["value"]
        elif n.get("name") == "HH token (cache)":
            m = re.search(r"store\.hh_token\s*\|\|\s*'([^']+)'", params.get("jsCode", ""))
            if m:
                out["seed"] = m.group(1)
    return out


def main():
    if not N8N_KEY:
        sys.exit("Задай N8N_KEY (n8n → Settings → n8n API).")
    global HH_CLIENT_ID, HH_CLIENT_SECRET, HH_SEED_TOKEN
    wf_id = os.environ.get("N8N_WF_ID") or _find_wf_id_by_name(WF_NAME)
    # HH-креды нужны при сборке (вшиваются в узел минта). Если их нет в env — берём из
    # существующего воркфлоу, чтобы не перевыпускать его с пустыми ключами.
    if not (HH_CLIENT_ID and HH_CLIENT_SECRET):
        creds = _existing_hh_creds(wf_id)
        HH_CLIENT_ID = HH_CLIENT_ID or creds.get("client_id", "")
        HH_CLIENT_SECRET = HH_CLIENT_SECRET or creds.get("client_secret", "")
        HH_SEED_TOKEN = HH_SEED_TOKEN or creds.get("seed", "")
        if HH_CLIENT_ID and HH_CLIENT_SECRET:
            print("HH-креды взяты из текущего воркфлоу (в .env не заданы)")
    if not (HH_CLIENT_ID and HH_CLIENT_SECRET):
        sys.exit("Нет HH_CLIENT_ID/HH_CLIENT_SECRET ни в .env, ни в текущем воркфлоу — "
                 "не перевыпускаю (иначе HH-поиск сломается). Добавь их в .env (dev.hh.ru/admin).")
    wf = build()
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
