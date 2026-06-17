// findwork — скоринг релевантности вакансий для n8n (Code node, "Run Once for All Items").
// СГЕНЕРИРОВАНО из profile/profile.json через tools/make_n8n_node.py — правки вноси в профиль.
//
// Вход: items из ноды HH (GET /vacancies) — у каждого item.json поля HH (name, snippet, salary,
//        alternate_url, employer, area, id, published_at).
// Выход: только релевантные (score >= порога дайджеста), отсортированы по score; добавлены
//        поля score/verdict/best_role/matched.

const PROFILE = {
"candidate": {
"name": "Скворцов Павел Валерьевич",
"city": "Москва",
"age": 39,
"phone": "+7 926 390-74-60",
"email": "sunpavel@mail.ru",
"telegram": "@sunpavel",
"languages": {
"русский": "родной",
"английский": "B1"
},
"experience_years": 16,
"relocation": false,
"ready_for_business_trips": true
},
"target_roles": [
{
"code": "CMO",
"name": "Директор по маркетингу",
"weight": 1.0,
"title_keywords": [
"директор по маркетингу",
"директор по маркетингу и pr",
"cmo",
"руководитель маркетинга",
"head of marketing",
"директор департамента маркетинга",
"вице-президент по маркетингу",
"директор по маркетингу и продажам",
"маркетинг-директор",
"директор по бренду и маркетингу"
]
},
{
"code": "CCO",
"name": "Коммерческий директор",
"weight": 1.0,
"title_keywords": [
"коммерческий директор",
"cco",
"директор по развитию",
"директор по продажам и маркетингу",
"commercial director",
"директор по коммерции",
"коммерческий директор по"
]
},
{
"code": "GROWTH",
"name": "Growth / продуктовый директор",
"weight": 0.8,
"title_keywords": [
"growth",
"директор по росту",
"head of growth",
"growth lead",
"директор по продукту",
"cpo",
"продуктовый маркетинг",
"директор по продуктовому маркетингу"
]
},
{
"code": "SALES",
"name": "Директор по продажам (смежная)",
"weight": 0.6,
"title_keywords": [
"директор по продажам",
"sales director",
"руководитель отдела продаж",
"head of sales"
]
}
],
"salary": {
"target_min": 600000,
"stretch": 900000,
"soft_floor": 450000,
"currency": "RUR",
"period": "month",
"note": "Ориентир — фикс на руки/мес. На hh вилки часто гросс и 'от', поэтому soft_floor мягкий."
},
"locations": {
"city": "Москва",
"hh_area_ids": [
1,
2019,
113
],
"relocation": false,
"formats": [
"remote",
"hybrid",
"office"
],
"format_is_strict": false
},
"skills": {
"маркетинговая стратегия": 1.0,
"стратегический маркетинг": 1.0,
"управление маркетингом": 1.0,
"коммерческий блок": 1.0,
"p&l": 1.0,
"юнит-экономика": 0.9,
"бюджетирование": 0.8,
"финансовая модель": 0.8,
"performance-маркетинг": 1.0,
"romi": 0.9,
"cac": 0.9,
"ltv": 0.9,
"cpl": 0.8,
"drr": 0.7,
"медиапланирование": 0.8,
"digital-маркетинг": 0.9,
"контекстная реклама": 0.7,
"яндекс.директ": 0.6,
"google ads": 0.6,
"таргетированная реклама": 0.6,
"smm": 0.6,
"seo": 0.6,
"aso": 0.5,
"serm": 0.5,
"orm": 0.5,
"брендинг": 0.9,
"позиционирование": 0.9,
"бренд-платформа": 0.8,
"ребрендинг": 0.7,
"pr": 0.9,
"связи с общественностью": 0.8,
"личный бренд": 0.7,
"crm-маркетинг": 0.9,
"crm": 0.7,
"amocrm": 0.5,
"воронка продаж": 0.8,
"retention": 0.8,
"удержание": 0.7,
"подписная модель": 0.7,
"сквозная аналитика": 0.9,
"roistat": 0.6,
"calltouch": 0.5,
"power bi": 0.6,
"google analytics": 0.5,
"яндекс.метрика": 0.5,
"управление командой": 1.0,
"построение отдела с нуля": 1.0,
"kpi": 0.7,
"okr": 0.7,
"управление подрядчиками": 0.6,
"запуск продукта": 1.0,
"go-to-market": 0.9,
"масштабирование": 1.0,
"вывод на рынок": 0.9,
"управление продажами": 0.9,
"отдел продаж": 0.8,
"пресейл": 0.7,
"ai-инструменты": 0.8,
"искусственный интеллект": 0.7,
"b2b": 0.9,
"b2b enterprise": 1.0,
"b2g": 0.9,
"b2c": 0.9,
"saas": 0.9,
"продуктовый маркетинг": 0.9,
"growth": 0.8
},
"industries": {
"it": 1.0,
"saas": 1.0,
"стартап": 0.9,
"разработка по": 0.9,
"девелопмент": 1.0,
"недвижимость": 1.0,
"строительство": 0.8,
"ритейл": 0.9,
"розничная сеть": 0.9,
"услуги для населения": 0.8,
"e-commerce": 0.8,
"реклама": 0.7,
"медиа": 0.7,
"финтех": 0.6,
"образование": 0.5
},
"stop_words": [
"junior",
"джуниор",
"стажёр",
"стажер",
"стажировка",
"ассистент",
"помощник",
"продавец-консультант",
"промоутер",
"вахта",
"подработка",
"курьер",
"оператор call",
"менеджер по продажам",
"специалист по маркетингу",
"smm-менеджер",
"smm менеджер",
"таргетолог",
"контент-менеджер",
"копирайтер",
"дизайнер",
"стажёр-маркетолог",
"без опыта"
],
"scoring_weights": {
"title": 0.4,
"skills": 0.35,
"salary": 0.1,
"industry": 0.15
},
"thresholds": {
"auto_apply": 80,
"digest": 55,
"skip_below": 40
}
};

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
