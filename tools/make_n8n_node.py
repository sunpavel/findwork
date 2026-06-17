#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерирует n8n/score_node.js — самодостаточный Code-node для n8n.

Зашивает профиль из profile/profile.json и портирует логику src/relevance.py на JS,
чтобы скоринг работал прямо в n8n (между HH-запросом и Telegram), без отдельного сервера.
Источник правды по профилю — profile.json; после его изменения перегенерируй узел.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
profile = json.loads((ROOT / "profile" / "profile.json").read_text(encoding="utf-8"))
PJSON = json.dumps(profile, ensure_ascii=False, indent=0)

JS = r'''// findwork — скоринг релевантности вакансий для n8n (Code node, "Run Once for All Items").
// СГЕНЕРИРОВАНО из profile/profile.json через tools/make_n8n_node.py — правки вноси в профиль.
//
// Вход: items из ноды HH (GET /vacancies) — у каждого item.json поля HH (name, snippet, salary,
//        alternate_url, employer, area, id, published_at).
// Выход: только релевантные (score >= порога дайджеста), отсортированы по score; добавлены
//        поля score/verdict/best_role/matched.

const PROFILE = __PROFILE__;

function norm(s){ return (s||'').toString().toLowerCase().replace(/ё/g,'е').replace(/\s+/g,' '); }
function esc(s){ return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'); }
function contains(hay, needle){
  needle = norm(needle);
  if (needle.length <= 4 && /^[\x00-\x7F]+$/.test(needle)) {
    return new RegExp('(?<![a-z])'+esc(needle)+'(?![a-z])').test(hay);
  }
  return hay.indexOf(needle) !== -1;
}
function rankedSkills(){
  return Object.entries(PROFILE.skills).sort((a,b)=>b[1]-a[1]);
}
function titleScore(titleN){
  let best=0, role='—';
  for (const r of PROFILE.target_roles){
    if (r.title_keywords.some(k=>contains(titleN,k)) && r.weight>best){ best=r.weight; role=r.name; }
  }
  return {score:best, role};
}
function skillsScore(textN){
  const ranked = rankedSkills();
  const sat = ranked.slice(0,12).reduce((s,[,w])=>s+w,0) || 1;
  let matchedW=0; const matched=[];
  for (const [skill,w] of ranked){ if (contains(textN,skill)){ matched.push(skill); matchedW+=w; } }
  const missing = ranked.filter(([s])=>!matched.includes(s)).slice(0,8).map(([s])=>s);
  return {score: Math.min(1, matchedW/sat), matched, missing};
}
function salaryScore(sal){
  const t=PROFILE.salary.target_min, floor=PROFILE.salary.soft_floor;
  if (!sal || (!sal.from && !sal.to)) return {score:0.6, note:'вилка не указана'};
  const top = sal.to || sal.from;
  if (top>=t) return {score:1.0, note:'вилка ≥ цели'};
  if (top>=floor) return {score:0.7, note:'ниже цели, выше пола'};
  return {score:0.2, note:'заметно ниже ожиданий'};
}
function industryScore(textN){
  const hits=Object.entries(PROFILE.industries).filter(([n])=>contains(textN,n)).map(([,w])=>w);
  return hits.length ? Math.min(1, Math.max(...hits)) : 0.5;
}
function redFlags(titleN,textN){
  const f=[];
  for (const w of PROFILE.stop_words){
    if (contains(titleN,w)) f.push('title:'+w); else if (contains(textN,w)) f.push(w);
  }
  return [...new Set(f)].slice(0,6);
}
function scoreVacancy(title, desc, salary){
  const titleN=norm(title), textN=norm(title+'. '+(desc||''));
  const t=titleScore(titleN), s=skillsScore(textN), sal=salaryScore(salary), ind=industryScore(textN);
  const flags=redFlags(titleN,textN);
  const w=PROFILE.scoring_weights;
  let raw = t.score*w.title + s.score*w.skills + sal.score*w.salary + ind*w.industry;
  const penalty = flags.reduce((p,f)=>p+(f.startsWith('title:')?0.12:0.06),0);
  const score = Math.round(Math.max(0,Math.min(1, raw-penalty))*100);
  const th=PROFILE.thresholds;
  let verdict = score>=th.auto_apply ? '🔥 топ-матч' : score>=th.digest ? '✅ в дайджест'
              : score>=th.skip_below ? '🤔 пограничная' : '✖ мимо';
  return {score, verdict, best_role:t.role, matched:s.matched.slice(0,8), red_flags:flags, salary_note:sal.note};
}

// --- маппинг вакансии HH → наш скоринг ---
function fromHH(v){
  const sn=v.snippet||{};
  return {
    id: v.id ? 'hh-'+v.id : (v.id||''),
    title: v.name || v.title || '',
    company: (v.employer||{}).name || v.company || '',
    url: v.alternate_url || v.url || '',
    area: (v.area||{}).name || v.area || '',
    salary: v.salary || null,
    published_at: v.published_at || '',
    description: [sn.requirement, sn.responsibility, v.description].filter(Boolean).join(' '),
  };
}

// --- glue для n8n (если запущено в n8n) ---
if (typeof $input !== 'undefined') {
  const out = [];
  for (const item of $input.all()) {
    const v = fromHH(item.json);
    const r = scoreVacancy(v.title, v.description, v.salary);
    if (r.score >= PROFILE.thresholds.digest) out.push({ json: { ...v, ...r } });
  }
  out.sort((a,b)=>b.json.score-a.json.score);
  return out;
}

// --- экспорт для локального теста под node ---
if (typeof module !== 'undefined') { module.exports = { scoreVacancy, fromHH, PROFILE }; }
'''

out = JS.replace("__PROFILE__", PJSON)
(ROOT / "n8n").mkdir(exist_ok=True)
dest = ROOT / "n8n" / "score_node.js"
dest.write_text(out, encoding="utf-8")
print(f"written {dest} ({dest.stat().st_size} bytes)")
