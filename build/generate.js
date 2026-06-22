/* Static multi-page generator for Skvortsov ADV */
const fs = require('fs');
const path = require('path');
const ROOT = require('path').join(__dirname, '..', 'site');
const VER = '11';

const BASE = 'https://skvortsovadv.ru';
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function head(o){
  const canonical = BASE + o.path;
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#0A0D13" />
  <title>${esc(o.title)}</title>
  <meta name="description" content="${esc(o.desc)}" />
  <meta name="robots" content="index, follow, max-image-preview:large" />
  <link rel="canonical" href="${canonical}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Skvortsov ADV" />
  <meta property="og:title" content="${esc(o.title)}" />
  <meta property="og:description" content="${esc(o.desc)}" />
  <meta property="og:url" content="${canonical}" />
  <meta property="og:locale" content="ru_RU" />
  <meta property="og:image" content="${BASE}/og-image.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="apple-touch-icon" href="/favicon.svg" />
  <link rel="preload" href="/fonts.css?v=${VER}" as="style" />
  <link rel="stylesheet" href="/fonts.css?v=${VER}" />
  <link rel="preload" href="/styles.css?v=${VER}" as="style" />
  <link rel="stylesheet" href="/styles.css?v=${VER}" />
  ${o.jsonld ? '<script type="application/ld+json">'+JSON.stringify(o.jsonld)+'</script>' : ''}
</head>
<body>
  <a class="skip-link" href="#main">Перейти к содержанию</a>
  <div class="bg-decor" aria-hidden="true"><div class="blob blob-1"></div><div class="blob blob-2"></div><div class="grid-overlay"></div></div>
  <header class="site-header" id="top">
    <div class="container header-inner">
      <a class="brand" href="/" aria-label="Skvortsov ADV — на главную"><img class="brand-mark" src="/logo.svg" width="38" height="34" alt="" aria-hidden="true" /><span class="brand-text">Skvortsov<strong>ADV</strong></span></a>
      <nav class="nav" aria-label="Основная навигация">
        <a href="/services/">Услуги</a>
        <a href="/cases/">Кейсы</a>
        <a href="/about/">Обо мне</a>
        <a href="/blog/">Блог</a>
      </nav>
      <a class="btn btn-primary btn-sm" href="/#audit">Бесплатный аудит</a>
      <button class="nav-toggle" aria-label="Меню" aria-expanded="false" aria-controls="mobile-nav"><span></span><span></span><span></span></button>
    </div>
    <nav class="mobile-nav" id="mobile-nav" aria-label="Мобильная навигация" hidden>
      <a href="/services/">Услуги</a>
      <a href="/cases/">Кейсы</a>
      <a href="/about/">Обо мне</a>
      <a href="/blog/">Блог</a>
      <a class="btn btn-primary" href="/#audit">Бесплатный аудит</a>
    </nav>
  </header>
  <main id="main">`;
}

function crumbs(items){
  return '<nav class="breadcrumbs" aria-label="Хлебные крошки">' +
    items.map((it,i)=> (it.href?`<a href="${it.href}">${esc(it.t)}</a>`:`<span>${esc(it.t)}</span>`) + (i<items.length-1?' <span>/</span> ':'')).join('') +
    '</nav>';
}

function ctaBand(title, sub){
  return `<section class="cta-band"><div class="container cta-inner"><div><h2>${esc(title)}</h2><p>${esc(sub)}</p></div><a class="btn btn-primary btn-lg" href="/#audit">Заказать консультацию</a></div></section>`;
}

function foot(){
  return `</main>
  <footer class="site-footer">
    <div class="container footer-inner">
      <div class="footer-brand">
        <a class="brand" href="/"><img class="brand-mark" src="/logo.svg" width="38" height="34" alt="" aria-hidden="true" /><span class="brand-text">Skvortsov<strong>ADV</strong></span></a>
        <p class="footer-tagline">Агентство роста, которое строит маркетинговые системы для масштабирования бизнеса — без пустых обещаний, накруток и слитых бюджетов.</p>
      </div>
      <div class="footer-contacts">
        <a href="/services/">Все услуги</a>
        <a href="/cases/">Кейсы</a>
        <a href="https://t.me/SkvortsovADV" target="_blank" rel="noopener">Telegram @SkvortsovADV</a>
        <a href="mailto:sunpavel@gmail.com">sunpavel@gmail.com</a>
      </div>
    </div>
    <div class="container footer-bottom"><span>© <span id="year">2026</span> Skvortsov ADV</span><span class="footer-legal"><a href="/privacy/">Политика конфиденциальности</a><a href="/terms/">Пользовательское соглашение</a><a href="/cookies/">Правила cookie</a></span></div>
  </footer>
  <script src="/script.js?v=${VER}" defer></script>
</body>
</html>`;
}

const CHECK = '<span class="fi"><svg viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg></span>';

function write(p, html){
  const dir = path.join(ROOT, p);
  fs.mkdirSync(dir, {recursive:true});
  fs.writeFileSync(path.join(dir,'index.html'), html);
  console.log('  ✓ /'+p+'/');
}

/* ---------------- Services data ---------------- */
const services = [
  {slug:'fractional-cmo', nav:'Fractional CMO', h1:'Fractional CMO — директор по маркетингу по подписке',
   desc:'Директор по маркетингу на аутсорсе: стратегия, найм команды, рост выручки — без затрат на штатного топ-менеджера.',
   lead:'Директор по маркетингу на аутсорсе. Стратегия, найм команды, рост выручки — без затрат на штатного топ-менеджера.',
   inT:'Что входит в услугу', inc:['Аудит маркетинга и продаж за 7 дней','Разработка стратегии роста','Найм и управление командой','Постановка целей и KPI','Внедрение CRM и аналитики','Регулярные встречи и отчёты','Оптимизация маркетингового бюджета','Масштабирование процессов'],
   suits:['Стартапам на стадии Product-Market Fit','Компаниям с выручкой 50–500 млн ₽/год','B2B с циклом сделки больше 3 месяцев','Девелоперам и застройщикам','Tech-компаниям (SaaS, PropTech, FinTech)'],
   rT:'Результаты работы', rType:'stats', res:[['+140%','Средний рост лидов'],['−35%','Снижение CAC'],['×2–8','Рост выручки за год']]},

  {slug:'abm-b2b', nav:'ABM-маркетинг', h1:'ABM-маркетинг для B2B',
   desc:'Account-Based Marketing: персонализированные кампании для крупных клиентов с CRM-интеграцией и атрибуцией сделок.',
   lead:'Персонализированные кампании для крупных клиентов с полной CRM-интеграцией и атрибуцией сделок.',
   inT:'Что включает ABM-стратегия', inc:['Идентификация целевых аккаунтов','Персонализированный контент','LinkedIn Sales Navigator','Email-цепочки для ЛПР','Ретаргетинг на компании','Интеграция с CRM (AmoCRM, Битрикс24)','Атрибуция сделок по аккаунтам','Sales enablement материалы'],
   suits:['B2B с чеком сделки от 1 млн ₽','Длинный цикл продаж (3+ месяца)','Продажи через тендеры и ЛПР','SaaS, Tech, промышленность','Девелопмент и строительство'],
   rT:'Результаты ABM-кампаний', rType:'stats', res:[['15–25%','Конверсия аккаунт → встреча'],['−40%','Снижение стоимости лида'],['300–500%','ROI кампании']]},

  {slug:'construction-tech', nav:'Маркетинг девелопмента', h1:'Маркетинг для девелопмента и строительства',
   desc:'Маркетинг недвижимости, BIM и PropTech: позиционирование объектов, лидогенерация и стратегия роста продаж.',
   lead:'Специализация на недвижимости, BIM, PropTech и строительных технологиях. Генерация лидов и стратегия роста.',
   inT:'Что входит в услугу', inc:['Позиционирование ЖК и объектов','Стратегия продаж через застройщика','Performance для лидогенерации','CRM для отдела продаж','Контент-стратегия (3D, рендеры)','Работа с агентствами недвижимости','Аналитика воронки продаж','Автоматизация маркетинга'],
   suits:['Девелоперы коммерческой недвижимости','Застройщики жилья (ЖК)','Управляющие компании','PropTech-стартапы (BIM, цифровизация)','Производители стройматериалов'],
   rT:'Результаты', rType:'stats', res:[['+180%','Рост лидов на объект'],['−45%','Снижение CPL'],['25–30%','Конверсия лид → встреча']]},

  {slug:'ai-marketing', nav:'AI-автоматизация', h1:'Автоматизация маркетинга и AI-агенты',
   desc:'Внедрение AI-агентов, n8n-автоматизация и интеграция систем для роста эффективности маркетинга.',
   lead:'Внедрение AI-агентов, n8n-автоматизация, интеграция систем для роста эффективности маркетинга.',
   inT:'Что автоматизируем', inc:['Обработка лидов и квалификация','Email/WhatsApp цепочки','Персонализация контента','Аналитика и отчёты','Интеграция CRM и рекламы','Чат-боты и AI-ассистенты','Автоматизация через n8n','Предиктивная аналитика'],
   suits:['B2B с потоком лидов больше 500/мес','E-commerce с большой базой клиентов','SaaS-компании с freemium-моделью','Агентства и консалтинг','Компании с 5+ маркетинговыми инструментами'],
   rT:'Результаты автоматизации', rType:'stats', res:[['15–20 ч/нед','Экономия времени маркетолога'],['−60%','Снижение операционных затрат'],['×10','Скорость обработки лидов']]},

  {slug:'brand-strategy', nav:'Бренд-стратегия', h1:'Бренд-стратегия и позиционирование',
   desc:'Позиционирование, JTBD, бренд-платформа и коммуникационная стратегия для выхода на рынок.',
   lead:'Позиционирование, JTBD, бренд-платформа и коммуникационная стратегия для выхода на рынок.',
   inT:'Что входит в услугу', inc:['Исследование рынка и конкурентов','Jobs-to-be-Done (JTBD)','Позиционирование бренда','Бренд-платформа и архетип','Tone-of-voice и манифест','Коммуникационная стратегия','Медиа-карта и каналы','Ценностные предложения (value prop)'],
   suits:['Запуск нового продукта или бренда','Ребрендинг и репозиционирование','Выход на новый рынок','B2B с длинным циклом продаж','Premium и luxury сегмент'],
   rT:'Результаты', rType:'stats', res:[['+200%','Рост узнаваемости бренда'],['+80%','Рост конверсии на сайте'],['−30%','Снижение стоимости привлечения']]},

  {slug:'pr-media', nav:'PR и медиа', h1:'PR и медиа',
   desc:'Работа с прессой, спикерство, медийные кампании и репутационный менеджмент для бизнеса.',
   lead:'Работа с прессой, спикерство, медийные кампании и репутационный менеджмент для бизнеса.',
   inT:'Что входит в услугу', inc:['Медиапланирование и стратегия','Работа с федеральными СМИ','Подготовка пресс-релизов','Спикерство на мероприятиях','Интервью и экспертные комментарии','Кризисный PR','Репутационный менеджмент','Мониторинг упоминаний'],
   suits:['Публикации в Forbes, РБК, Коммерсант','Спикер на конференциях и форумах','Экспертные комментарии для СМИ','Работа с отраслевыми изданиями','Управление репутацией брендов'],
   rT:'Результаты', rType:'stats', res:[['5M+','Охват аудитории за кампанию'],['50+','Публикаций в федеральных СМИ'],['+300%','Рост узнаваемости бренда']]},

  {slug:'web-development', nav:'Создание сайтов', h1:'Создание сайтов, которые продают',
   desc:'Разработка сайтов под результат: от лендингов до корпоративных порталов и e-commerce решений.',
   lead:'Разрабатываем сайты, которые продают: от лендингов до сложных корпоративных порталов и e-commerce решений.',
   inT:'Что входит в услугу', incType:'features', inc:[
     {t:'Landing Page',d:'Одностраничники с высокой конверсией для рекламных кампаний'},
     {t:'Корпоративные сайты',d:'Многостраничные порталы с удобной CMS для управления контентом'},
     {t:'E-commerce',d:'Интернет-магазины с интеграцией платёжных систем и складского учёта'},
     {t:'Адаптивный дизайн',d:'Корректное отображение на всех устройствах и экранах'}],
   suits:['B2B-компании — презентация услуг и лиды','E-commerce — онлайн-продажи и каталог','Стартапы — MVP для теста гипотез','Производители — витрина продукции'],
   rT:'Результат', rType:'features', res:[
     {t:'Высокая конверсия',d:'Фокус на действия пользователя и чёткие CTA'},
     {t:'Быстрая загрузка',d:'Оптимизация производительности и Core Web Vitals'},
     {t:'Mobile-first',d:'Приоритет мобильной версии для всех устройств'},
     {t:'SEO-ready',d:'Техническая оптимизация для поисковых систем'}]},

  {slug:'automation', nav:'Автоматизация & CRM', h1:'Автоматизация & CRM',
   desc:'Внедрение CRM-систем и автоматизация процессов для увеличения продаж и эффективности бизнеса.',
   lead:'Внедряем CRM-системы и автоматизируем процессы для увеличения продаж и эффективности бизнеса.',
   inT:'Что входит в услугу', incType:'features', inc:[
     {t:'Внедрение CRM',d:'Настройка amoCRM, Bitrix24, HubSpot под ваши бизнес-процессы'},
     {t:'Email-маркетинг',d:'Автоматические цепочки писем, сегментация, A/B-тесты'},
     {t:'Колл-центры',d:'Организация исходящих и входящих звонков, интеграция с CRM'},
     {t:'Автоматизация продаж',d:'Воронки, триггеры, скоринг лидов, автоотчёты'}],
   suits:['Отделы продаж — контроль воронки и KPI','B2B — длинные циклы сделок и ABM','E-commerce — коммуникации с клиентами','Сервисные компании — проекты и база'],
   rT:'Результат', rType:'features', res:[
     {t:'+30–50% конверсия',d:'Автоматизация follow-up и персонализация коммуникаций'},
     {t:'Экономия времени',d:'Автоматизация рутинных операций и отчётности'},
     {t:'Прозрачность',d:'Полная видимость воронки и атрибуция источников'},
     {t:'Контроль качества',d:'Записи звонков, скрипты, контроль KPI менеджеров'}]},

  {slug:'ai-implementation', nav:'Внедрение ИИ', h1:'Внедрение ИИ в маркетинг и коммуникации',
   desc:'Автоматизируем маркетинг и коммуникации с помощью ИИ — от колл-центров до генерации контента.',
   lead:'Автоматизируем маркетинг и коммуникации с помощью искусственного интеллекта — от колл-центров до генерации контента.',
   inT:'Что входит в услугу', incType:'features', inc:[
     {t:'ИИ колл-центры',d:'Голосовые боты для обработки входящих и исходящих звонков 24/7'},
     {t:'Автопостинг',d:'Генерация и публикация контента в соцсетях на основе ИИ'},
     {t:'Чат-боты',d:'Умные ассистенты для сайта, WhatsApp, Telegram с NLP'},
     {t:'Генерация контента',d:'Тексты, креативы, видео на основе ваших данных и бренда'}],
   suits:['E-commerce — поддержка и продажи','Сервисные компании — обработка заявок','Контент-проекты — масштабирование','B2B-продажи — квалификация лидов'],
   rT:'Результат', rType:'features', res:[
     {t:'Снижение затрат',d:'Экономия до 70% на персонале колл-центра и контенте'},
     {t:'Мгновенный отклик',d:'Обработка обращений 24/7 без выходных и задержек'},
     {t:'Масштабируемость',d:'Тысячи запросов одновременно без найма персонала'},
     {t:'Персонализация',d:'Адаптация коммуникаций под каждого клиента по данным'}]},
];

function renderIncludes(s){
  if(s.incType==='features'){
    return '<div class="feature-grid">'+s.inc.map(f=>`<div class="feature">${CHECK}<div><h4>${esc(f.t)}</h4><p>${esc(f.d)}</p></div></div>`).join('')+'</div>';
  }
  return '<ul class="bullet bullet-check">'+s.inc.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>';
}
function renderResults(s){
  if(s.rType==='features'){
    return '<div class="feature-grid">'+s.res.map(f=>`<div class="feature">${CHECK}<div><h4>${esc(f.t)}</h4><p>${esc(f.d)}</p></div></div>`).join('')+'</div>';
  }
  return '<div class="stat-grid">'+s.res.map(r=>`<div class="stat"><strong>${esc(r[0])}</strong><span>${esc(r[1])}</span></div>`).join('')+'</div>';
}

/* ---- Service detail pages ---- */
services.forEach(s=>{
  const jsonld={"@context":"https://schema.org","@type":"Service","name":s.h1,"description":s.desc,"provider":{"@type":"Person","name":"Павел Скворцов"},"areaServed":"RU","url":BASE+'/services/'+s.slug+'/'};
  const body = `
  <section class="page-hero">
    <div class="container">
      ${crumbs([{t:'Главная',href:'/'},{t:'Услуги',href:'/services/'},{t:s.nav}])}
      <span class="eyebrow"><span class="dot"></span>Услуга</span>
      <h1>${esc(s.h1)}</h1>
      <p class="lead">${esc(s.lead)}</p>
      <div class="page-cta"><a class="btn btn-primary btn-lg" href="/#audit">Заказать консультацию</a><a class="btn btn-ghost btn-lg" href="https://t.me/SkvortsovADV" target="_blank" rel="noopener">Написать в Telegram</a></div>
    </div>
  </section>
  <section class="section">
    <div class="container two-col">
      <div><h2 class="block-title">${esc(s.inT)}</h2>${renderIncludes(s)}</div>
      <div><h2 class="block-title">Кому подходит</h2><ul class="bullet">${s.suits.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
    </div>
  </section>
  <section class="section section-alt">
    <div class="container">
      <div class="section-head"><span class="eyebrow"><span class="dot"></span>Результаты</span><h2>${esc(s.rT)}</h2></div>
      ${renderResults(s)}
    </div>
  </section>
  ${ctaBand('Обсудим вашу задачу?','Бесплатный аудит роста за 7 дней — без обязательств.')}`;
  write('services/'+s.slug, head({title:s.h1+' — Skvortsov ADV',desc:s.desc,path:'/services/'+s.slug+'/',jsonld})+body+foot());
});

/* ---- Services overview ---- */
(function(){
  const cards = services.map(s=>`<a class="card svc-card" href="/services/${s.slug}/"><h3>${esc(s.nav)}</h3><p>${esc(s.lead)}</p><span class="svc-arrow">Подробнее →</span></a>`).join('');
  const body=`
  <section class="page-hero">
    <div class="container">
      ${crumbs([{t:'Главная',href:'/'},{t:'Услуги'}])}
      <span class="eyebrow"><span class="dot"></span>Услуги</span>
      <h1>Услуги маркетингового агентства</h1>
      <p class="lead">Полный цикл маркетинга под одним управлением: стратегия, performance, B2B/ABM, аналитика, привлечение инвестиций, AI-автоматизация и разработка.</p>
      <div class="page-cta"><a class="btn btn-primary btn-lg" href="/#audit">Бесплатный аудит</a></div>
    </div>
  </section>
  <section class="section"><div class="container"><div class="grid svc-index-grid">${cards}</div></div></section>
  ${ctaBand('Не знаете, с чего начать?','Разберём вашу воронку и найдём точки роста за 7 дней.')}`;
  write('services', head({title:'Услуги маркетингового агентства — Павел Скворцов',desc:'9 направлений: Fractional CMO, ABM для B2B, маркетинг девелопмента, AI-автоматизация, бренд-стратегия, PR, разработка сайтов, CRM, внедрение ИИ.',path:'/services/'})+body+foot());
})();

/* ---- Cases (data-driven executive portfolio) ---- */
(function(){
  const cases = require('./cases-data.json').slice().sort((a,b)=>(a.priority||99)-(b.priority||99));
  const industries = ['Все', ...Array.from(new Set(cases.map(c=>c.industry)))];
  const hm = m => `<div class="cm"><strong>${esc(m.v)}</strong><span>${esc(m.l)}</span></div>`;
  const meta = c => [c.role,c.period].filter(x=>x&&x!=='—').map(esc).join(' · ');

  function card(c){
    const cover = (c.assets&&c.assets.length)
      ? `<div class="pcase-cover"><img src="${c.assets[0]}" alt="${esc(c.company)}" loading="lazy" width="820" height="470" /></div>`
      : `<div class="pcase-cover pcase-ph"><span>${esc(c.company)}</span></div>`;
    const head2 = `<div class="pcase-head"><h3>${esc(c.company)}</h3>${c.project&&c.project!=='—'?`<p class="pcase-proj">${esc(c.project)}</p>`:''}${meta(c)?`<p class="pcase-meta">${meta(c)}</p>`:''}</div>`;
    const more = c.short ? '' : `<a class="pcase-more" href="/cases/${c.slug}/">Подробнее →</a>`;
    return `<article class="pcase-card${c.short?' pcase-short':''}" data-industry="${esc(c.industry)}"${c.short?'':` data-href="/cases/${c.slug}/"`}>${cover}<div class="pcase-body"><span class="ind-tag">${esc(c.industry)}</span>${head2}<p class="pcase-teaser">${esc(c.teaser)}</p><div class="pcase-metrics">${(c.heroMetrics||[]).slice(0,3).map(hm).join('')}</div>${more}</div></article>`;
  }
  const tabs = industries.map((i,idx)=>`<button class="filter-tab${idx===0?' active':''}" type="button" data-filter="${i==='Все'?'all':esc(i)}">${esc(i)}</button>`).join('');
  const body = `
  <section class="page-hero"><div class="container">
    ${crumbs([{t:'Главная',href:'/'},{t:'Кейсы'}])}
    <span class="eyebrow"><span class="dot"></span>Портфолио</span>
    <h1>Кейсы и результаты</h1>
    <p class="lead">17+ лет в девелопменте, IT/SaaS и сервисных сетях. Каждый кейс — по схеме «Задача → Что сделал → Результат» с конкретными цифрами.</p>
  </div></section>
  <section class="section" style="padding-top:22px"><div class="container">
    <div class="case-filter" role="tablist" aria-label="Фильтр по индустрии">${tabs}</div>
    <div class="grid pcases-grid">${cases.map(card).join('')}</div>
  </div></section>
  ${ctaBand('Обсудим сотрудничество?','Открыт к сильным продуктовым и executive-ролям. Связаться удобно в Telegram или по почте.')}`;
  write('cases', head({title:'Кейсы и портфолио — Павел Скворцов (CMO/CCO)',desc:'Портфолио проектов Павла Скворцова: TERMOLAND, ASTERUS/ALIA, Главстрой, Space 1, Pragmacore, Rukki, НДВ. Девелопмент, IT/SaaS, сервисные сети.',path:'/cases/',jsonld:{"@context":"https://schema.org","@type":"CollectionPage","name":"Кейсы и портфолио","url":BASE+'/cases/'}})+body+foot());

  // detail pages
  cases.filter(c=>!c.short).forEach(c=>{
    const plates = (c.results||[]).filter(r=>r.v!==undefined).map(r=>`<div class="stat"><strong>${esc(r.v)}</strong><span>${esc(r.l)}</span></div>`).join('');
    const notes = (c.results||[]).filter(r=>r.note).map(r=>`<li>${esc(r.note)}</li>`).join('');
    const heroImg = (c.assets&&c.assets.length)?`<section class="section" style="padding:22px 0"><div class="container"><div class="dcase-cover"><img src="${c.assets[0]}" alt="${esc(c.company)}" width="1200" height="560" loading="lazy" /></div></div></section>`:'';
    const tools = (c.tools&&c.tools.length)?`<div class="dcase-block"><h2 class="block-title">Инструменты и каналы</h2><ul class="tags tags-wrap">${c.tools.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`:'';
    const links = (c.links&&c.links.length)?`<div class="dcase-block"><h2 class="block-title">Ссылки</h2><ul class="link-list">${c.links.map(l=>`<li><a href="${l.url}" target="_blank" rel="noopener">${esc(l.label)} ↗</a></li>`).join('')}</ul></div>`:'';
    const detail = `
    <section class="page-hero"><div class="container">
      ${crumbs([{t:'Главная',href:'/'},{t:'Кейсы',href:'/cases/'},{t:c.company}])}
      <span class="ind-tag">${esc(c.industry)}</span>
      <h1>${esc(c.company)}</h1>
      ${c.project&&c.project!=='—'?`<p class="dcase-project">${esc(c.project)}</p>`:''}
      ${meta(c)?`<p class="dcase-meta">${meta(c)}</p>`:''}
      <div class="pcase-metrics dcase-hero-metrics">${(c.heroMetrics||[]).map(hm).join('')}</div>
    </div></section>
    ${heroImg}
    <section class="section" style="padding-top:${heroImg?'8':'22'}px"><div class="container dcase-wrap">
      <div class="dcase-block"><h2 class="block-title">Задача</h2><p class="dcase-text">${esc(c.context)}</p></div>
      <div class="dcase-block"><h2 class="block-title">Что сделал</h2><ul class="bullet">${(c.actions||[]).map(a=>`<li>${esc(a)}</li>`).join('')}</ul></div>
      <div class="dcase-block"><h2 class="block-title">Результаты</h2>${plates?`<div class="stat-grid">${plates}</div>`:''}${notes?`<ul class="bullet" style="margin-top:18px">${notes}</ul>`:''}</div>
      ${tools}${links}
      <p style="margin-top:26px"><a class="btn btn-ghost" href="/cases/">← Все кейсы</a></p>
    </div></section>
    ${ctaBand('Заинтересовал кейс?','Расскажу детали и цифры — пишите в Telegram или на почту.')}`;
    const jsonld={"@context":"https://schema.org","@type":"CreativeWork","name":c.company+(c.project&&c.project!=='—'?' — '+c.project:''),"about":c.industry,"creator":{"@type":"Person","name":"Павел Скворцов"},"url":BASE+'/cases/'+c.slug+'/'};
    write('cases/'+c.slug, head({title:c.company+' — кейс · Павел Скворцов',desc:c.teaser,path:'/cases/'+c.slug+'/',jsonld})+detail+foot());
  });
})();

/* ---- About ---- */
(function(){
  const tools=['Power BI','Data Studio','Calltouch','AmoCRM','Notion','ChatGPT','Midjourney','Figma','Tilda'];
  const exp=['Сертификации Google / Яндекс','Обучение в HSE (Digital strategy), Sber 500, ФРИИ Спринт 7','16+ лет в IT, ритейле, urban-девелопменте','Топовые агентства: BBDO, Media Shtorm','Клиенты: ГК Основа, Termoland, Pragmacore, Asterus, Space 1, Ametyst Group, Zolla, Unisaw'];
  const pillars=[['01','Системность','Не разовые кампании, а системы маркетинга, которые работают долгосрочно'],['02','Данные','Решения основаны на данных и аналитике, а не на предположениях'],['03','Результат','Фокус на метриках, которые напрямую влияют на прибыль бизнеса']];
  const body=`
  <section class="page-hero"><div class="container">${crumbs([{t:'Главная',href:'/'},{t:'Обо мне'}])}<span class="eyebrow"><span class="dot"></span>Обо мне</span><h1>Эксперт по системному маркетингу и росту бизнеса</h1></div></section>
  <section class="section" style="padding-top:20px"><div class="container about-grid">
    <div class="about-side">
      <div class="avatar"><img src="/img/pavel.jpg" alt="Павел Скворцов — маркетинговый стратег, fractional CMO" width="620" height="744" /><span class="avatar-badge">16+ лет</span></div>
      <div class="about-quick"><div><strong>BBDO Group</strong><span>экс-креативный директор</span></div><div><strong>HSE · Sber 500 · ФРИИ</strong><span>образование</span></div><div><strong>Google / Яндекс</strong><span>сертификации</span></div></div>
    </div>
    <div class="about-text">
      <h2>Павел Скворцов</h2>
      <p class="about-role">Маркетинговый стратег · Fractional CMO · Масштабирование бизнеса · Инвестиции</p>
      <p>Эксперт по системному маркетингу и росту бизнеса с 16+ летним опытом. Специализируюсь на IT, ритейле, urban-девелопменте, B2C и B2B. Был креативным директором в BBDO Group. Работал с Termoland, Pragmacore, Space 1, ASTERUS.</p>
      <p>Фокусируюсь на создании маркетинговых систем, которые масштабируются и дают предсказуемый рост выручки — а не на красивых отчётах.</p>
      <h4>Экспертиза</h4><ul class="bullet">${exp.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
      <h4>Инструменты</h4><ul class="tags tags-wrap">${tools.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
    </div>
  </div></section>
  <section class="section section-alt"><div class="container">
    <div class="section-head"><span class="eyebrow"><span class="dot"></span>Подход</span><h2>Наш подход</h2></div>
    <div class="grid approach-grid">${pillars.map(p=>`<article class="card"><span class="approach-num">${p[0]}</span><h3>${esc(p[1])}</h3><p>${esc(p[2])}</p></article>`).join('')}</div>
  </div></section>
  ${ctaBand('Готовы к росту?','Получите бесплатный аудит роста за 7 дней.')}`;
  write('about', head({title:'Обо мне — Павел Скворцов | Консультант по маркетингу',desc:'Павел Скворцов — маркетинговый стратег и fractional CMO с 16+ летним опытом. Экс-креативный директор BBDO. IT, ритейл, девелопмент, B2B.',path:'/about/',jsonld:{"@context":"https://schema.org","@type":"Person","name":"Павел Скворцов","jobTitle":"Маркетинговый стратег, Fractional CMO","url":BASE+'/about/',"sameAs":"https://t.me/SkvortsovADV"}})+body+foot());
})();

/* ---- Blog ---- */
(function(){
  const posts=[
    {tag:'Fractional CMO',h:'Fractional CMO: зачем бизнесу маркетинг-директор на аутсорсе',p:'Когда штатный CMO дорог и преждевременен, а маркетингом надо управлять системно — разбираем модель fractional и её экономику.'},
    {tag:'B2B / ABM',h:'ABM для B2B: как работать с крупными клиентами персонализированно',p:'Пошагово: от выбора целевых аккаунтов и контента для ЛПР до атрибуции сделок в CRM.'},
    {tag:'AI / Автоматизация',h:'AI-агенты в маркетинге: автоматизация через n8n',p:'Как связать лиды, CRM, рассылки и аналитику в единый автоматизированный контур на n8n и LLM.'},
  ];
  const cards=posts.map(p=>`<article class="card post"><span class="post-tag">${esc(p.tag)}</span><h3>${esc(p.h)}</h3><p>${esc(p.p)}</p><span class="post-soon">Скоро · полная статья готовится</span></article>`).join('');
  const body=`
  <section class="page-hero"><div class="container">${crumbs([{t:'Главная',href:'/'},{t:'Блог'}])}<span class="eyebrow"><span class="dot"></span>Блог</span><h1>Блог о маркетинге и стратегии бизнеса</h1><p class="lead">Практика системного маркетинга: fractional CMO, ABM, AI-автоматизация и рост выручки.</p></div></section>
  <section class="section" style="padding-top:24px"><div class="container"><div class="grid blog-grid">${cards}</div></div></section>
  ${ctaBand('Нужен системный маркетинг?','Бесплатный аудит роста за 7 дней.')}`;
  write('blog', head({title:'Блог о маркетинге и стратегии бизнеса | Павел Скворцов',desc:'Статьи о системном маркетинге: fractional CMO, ABM для B2B, AI-автоматизация на n8n, рост выручки и аналитика.',path:'/blog/'})+body+foot());
})();

/* ---- Privacy policy ---- */
(function(){
  const upd = '21 июня 2026 г.';
  const body = `
  <section class="page-hero"><div class="container">${crumbs([{t:'Главная',href:'/'},{t:'Политика конфиденциальности'}])}<h1>Политика конфиденциальности</h1></div></section>
  <section class="section" style="padding-top:16px"><div class="container legal">
    <p class="updated">Последнее обновление: ${upd}</p>

    <h2>1. Общие положения</h2>
    <p>Настоящая Политика в отношении обработки персональных данных (далее — «Политика») определяет порядок обработки и защиты персональных данных пользователей сайта <a href="https://skvortsovadv.ru/">skvortsovadv.ru</a> (далее — «Сайт»).</p>
    <p>Оператор персональных данных: Скворцов Павел (далее — «Оператор»). Контакт для обращений: <a href="mailto:sunpavel@gmail.com">sunpavel@gmail.com</a>, Telegram <a href="https://t.me/SkvortsovADV" target="_blank" rel="noopener">@SkvortsovADV</a>.</p>
    <p>Используя Сайт и отправляя данные через формы, пользователь подтверждает согласие с настоящей Политикой и даёт согласие на обработку персональных данных на изложенных условиях в соответствии с Федеральным законом № 152-ФЗ «О персональных данных».</p>

    <h2>2. Какие данные обрабатываются</h2>
    <ul>
      <li>Данные, которые вы добровольно указываете в формах: имя, номер телефона, адрес электронной почты, описание задачи.</li>
      <li>Технические данные, собираемые автоматически: cookie-файлы, IP-адрес, тип устройства и браузера, источник перехода, страницы и действия на Сайте (через системы веб-аналитики).</li>
    </ul>

    <h2>3. Цели обработки</h2>
    <ul>
      <li>обработка заявок и обратная связь с пользователем, консультации и подготовка аудита;</li>
      <li>улучшение работы Сайта, аналитика посещаемости и качества сервиса;</li>
      <li>исполнение требований законодательства РФ.</li>
    </ul>

    <h2>4. Правовые основания</h2>
    <p>Обработка осуществляется на основании согласия субъекта персональных данных, а также в целях исполнения договора или принятия мер по обращению пользователя.</p>

    <h2>5. Файлы cookie</h2>
    <p>Сайт использует файлы cookie и аналогичные технологии для корректной работы интерфейса, запоминания настроек и сбора обезличенной статистики. Вы можете отключить cookie в настройках браузера, однако это может ограничить функциональность Сайта. Продолжая пользоваться Сайтом, вы соглашаетесь с использованием cookie.</p>

    <h2>6. Передача третьим лицам</h2>
    <p>Оператор не продаёт и не передаёт персональные данные третьим лицам, за исключением случаев, предусмотренных законодательством РФ, а также привлечения поставщиков сервисов (хостинг, мессенджеры, системы аналитики и CRM), действующих по поручению Оператора и обеспечивающих конфиденциальность.</p>

    <h2>7. Сроки хранения</h2>
    <p>Персональные данные хранятся не дольше, чем этого требуют цели обработки, либо до отзыва согласия, после чего удаляются или обезличиваются.</p>

    <h2>8. Права пользователя</h2>
    <p>Вы вправе запросить информацию об обработке ваших данных, их уточнение, блокирование или удаление, а также отозвать согласие на обработку, направив обращение на <a href="mailto:sunpavel@gmail.com">sunpavel@gmail.com</a>.</p>

    <h2>9. Защита данных</h2>
    <p>Оператор принимает необходимые организационные и технические меры для защиты персональных данных от неправомерного доступа, изменения, раскрытия или уничтожения.</p>

    <h2>10. Изменения Политики</h2>
    <p>Оператор вправе изменять настоящую Политику. Актуальная редакция всегда размещается на данной странице.</p>
  </div></section>`;
  write('privacy', head({title:'Политика конфиденциальности — Skvortsov ADV',desc:'Политика обработки персональных данных и использования файлов cookie на сайте skvortsovadv.ru. Согласно 152-ФЗ.',path:'/privacy/'})+body+foot());
})();

/* ---- Terms of use ---- */
(function(){
  const upd='21 июня 2026 г.';
  const body=`
  <section class="page-hero"><div class="container">${crumbs([{t:'Главная',href:'/'},{t:'Пользовательское соглашение'}])}<h1>Пользовательское соглашение</h1></div></section>
  <section class="section" style="padding-top:16px"><div class="container legal">
    <p class="updated">Последнее обновление: ${upd}</p>

    <h2>1. Общие положения</h2>
    <p>Настоящее Пользовательское соглашение (далее — «Соглашение») регулирует отношения между владельцем сайта <a href="https://skvortsovadv.ru/">skvortsovadv.ru</a> (далее — «Администрация») и пользователем Сайта (далее — «Пользователь»). Используя Сайт, Пользователь подтверждает согласие с условиями Соглашения.</p>

    <h2>2. Предмет соглашения</h2>
    <p>Сайт предоставляет информацию об услугах маркетингового консультирования, кейсах и материалах. Через формы на Сайте Пользователь может оставить заявку на консультацию.</p>

    <h2>3. Использование Сайта</h2>
    <ul>
      <li>Пользователь обязуется указывать достоверные данные при отправке заявок.</li>
      <li>Запрещается использовать Сайт для незаконных действий, рассылки спама, попыток нарушить работу Сайта.</li>
      <li>Пользователь самостоятельно несёт ответственность за сохранность своих устройств и данных доступа.</li>
    </ul>

    <h2>4. Интеллектуальная собственность</h2>
    <p>Все материалы Сайта (тексты, графика, логотип, оформление) являются объектами интеллектуальной собственности и не могут использоваться без согласия Администрации.</p>

    <h2>5. Ограничение ответственности</h2>
    <p>Информация на Сайте носит справочный характер и не является публичной офертой. Администрация не гарантирует достижения конкретных результатов и не несёт ответственности за решения, принятые Пользователем на основе материалов Сайта, а также за временную недоступность Сайта.</p>

    <h2>6. Персональные данные и cookie</h2>
    <p>Обработка персональных данных осуществляется в соответствии с <a href="/privacy/">Политикой конфиденциальности</a>. Использование файлов cookie описано в <a href="/cookies/">Правилах использования файлов cookie</a>.</p>

    <h2>7. Изменения и применимое право</h2>
    <p>Администрация вправе изменять Соглашение в одностороннем порядке; актуальная редакция размещается на данной странице. К Соглашению применяется законодательство Российской Федерации.</p>

    <h2>8. Контакты</h2>
    <p>По вопросам, связанным с Соглашением: <a href="mailto:sunpavel@gmail.com">sunpavel@gmail.com</a>, Telegram <a href="https://t.me/SkvortsovADV" target="_blank" rel="noopener">@SkvortsovADV</a>.</p>
  </div></section>`;
  write('terms', head({title:'Пользовательское соглашение — Skvortsov ADV',desc:'Условия использования сайта skvortsovadv.ru: предмет, права и обязанности, ответственность, интеллектуальная собственность.',path:'/terms/'})+body+foot());
})();

/* ---- Cookie policy ---- */
(function(){
  const upd='21 июня 2026 г.';
  const body=`
  <section class="page-hero"><div class="container">${crumbs([{t:'Главная',href:'/'},{t:'Правила использования cookie'}])}<h1>Правила использования файлов cookie</h1></div></section>
  <section class="section" style="padding-top:16px"><div class="container legal">
    <p class="updated">Последнее обновление: ${upd}</p>

    <h2>1. Что такое cookie</h2>
    <p>Файлы cookie — это небольшие текстовые файлы, которые сохраняются в браузере при посещении сайта <a href="https://skvortsovadv.ru/">skvortsovadv.ru</a> и помогают сайту запоминать ваши действия и настройки, а также собирать обезличенную статистику.</p>

    <h2>2. Какие cookie мы используем</h2>
    <ul>
      <li><strong>Необходимые</strong> — обеспечивают базовую работу сайта и не могут быть отключены (например, запоминание согласия с использованием cookie).</li>
      <li><strong>Аналитические</strong> — помогают понять, как посетители пользуются сайтом (источники переходов, популярные страницы) для улучшения сервиса.</li>
      <li><strong>Функциональные</strong> — запоминают ваши предпочтения и улучшают удобство использования.</li>
    </ul>

    <h2>3. Цели использования</h2>
    <ul>
      <li>корректная работа интерфейса и форм;</li>
      <li>анализ посещаемости и качества сайта;</li>
      <li>повышение удобства и релевантности контента.</li>
    </ul>

    <h2>4. Согласие и управление</h2>
    <p>При первом посещении сайта вы видите уведомление об использовании cookie. Продолжая пользоваться сайтом или нажимая «Принять», вы соглашаетесь с использованием cookie. Вы можете в любой момент отключить или удалить cookie в настройках вашего браузера (Chrome, Safari, Firefox, Edge и др.). Отключение части cookie может ограничить функциональность сайта.</p>

    <h2>5. Сторонние сервисы</h2>
    <p>На сайте могут использоваться cookie сторонних сервисов веб-аналитики. Такие сервисы обрабатывают обезличенные данные в соответствии со своими политиками.</p>

    <h2>6. Связанные документы</h2>
    <p>Обработка персональных данных описана в <a href="/privacy/">Политике конфиденциальности</a>. Условия использования сайта — в <a href="/terms/">Пользовательском соглашении</a>.</p>

    <h2>7. Контакты</h2>
    <p>Вопросы по использованию cookie: <a href="mailto:sunpavel@gmail.com">sunpavel@gmail.com</a>.</p>
  </div></section>`;
  write('cookies', head({title:'Правила использования файлов cookie — Skvortsov ADV',desc:'Какие файлы cookie использует сайт skvortsovadv.ru, цели и управление настройками cookie в браузере.',path:'/cookies/'})+body+foot());
})();

console.log('\nDone.');
