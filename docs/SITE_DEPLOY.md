# Skvortsov ADV — запуск сайта на GitHub Pages + домены reg.ru

Сайт лежит в папке [`site/`](../site/) — это чистый статический сайт (HTML/CSS/JS,
без сборки). Деплой настроен через GitHub Actions
([`.github/workflows/deploy-site.yml`](../.github/workflows/deploy-site.yml)):
при пуше в `main` сайт автоматически публикуется на GitHub Pages.

Итог: сайт открывается на **https://skvortsovadv.ru** (и редирект с **s-adv.ru**),
работает в России без VPN, быстро грузится и хорошо индексируется поисковиками.

---

## Шаг 1. Влить ветку в `main`

Сейчас сайт на ветке `claude/eager-clarke-xgd1zc`. Workflow деплоит из `main`.

1. Открой Pull Request из `claude/eager-clarke-xgd1zc` в `main` и смёржи его
   (или вручную: `git checkout main && git merge claude/eager-clarke-xgd1zc && git push`).

> Можно сначала проверить локально: `cd site && python3 -m http.server 8080`
> и открыть http://localhost:8080

## Шаг 2. Включить GitHub Pages

1. Репозиторий → **Settings → Pages**.
2. **Build and deployment → Source:** выбери **GitHub Actions**.
3. После первого успешного запуска workflow (вкладка **Actions**) сайт будет
   доступен по адресу `https://<твой-логин>.github.io/...`, а затем — на домене (см. ниже).

## Шаг 3. Привязать домен skvortsovadv.ru (основной)

В файле [`site/CNAME`](../site/CNAME) уже указан `skvortsovadv.ru` — GitHub возьмёт его автоматически.

### DNS на reg.ru для `skvortsovadv.ru`

Зайди в reg.ru → твой домен → **Управление DNS / DNS-серверы и зона**.
Если домен использует DNS-серверы reg.ru (`ns1.reg.ru` / `ns2.reg.ru`) — редактируй зону там.

Добавь записи (удалив старые конфликтующие A/AAAA для `@`):

**A-записи (apex, имя `@` или пустое):**
```
@   A   185.199.108.153
@   A   185.199.109.153
@   A   185.199.110.153
@   A   185.199.111.153
```

**AAAA-записи (IPv6, опционально, но желательно):**
```
@   AAAA   2606:50c0:8000::153
@   AAAA   2606:50c0:8001::153
@   AAAA   2606:50c0:8002::153
@   AAAA   2606:50c0:8003::153
```

**Поддомен www → на GitHub:**
```
www   CNAME   <твой-логин>.github.io.
```

### Подтверждение в GitHub
1. **Settings → Pages → Custom domain:** впиши `skvortsovadv.ru`, **Save**.
2. Дождись зелёной галочки DNS check (DNS обновляется от минут до пары часов).
3. Включи **Enforce HTTPS** (сертификат Let's Encrypt выпустится автоматически).

## Шаг 4. Домен s-adv.ru → редирект на основной

GitHub Pages обслуживает только один домен (тот, что в `CNAME`), поэтому второй
делаем 301-редиректом.

**Вариант А (проще, рекомендуется):** в reg.ru для `s-adv.ru` включи
**«Перенаправление домена» (web-forwarding)** → `https://skvortsovadv.ru`, тип 301.

**Вариант Б:** если хочешь, чтобы оба домена открывали сайт напрямую — поменяй
их ролями (какой основной), либо подними лёгкий редирект на отдельном хостинге.
Для лидогенерации достаточно варианта А.

> Поменять основной домен на `s-adv.ru` легко: впиши `s-adv.ru` в `site/CNAME`,
> перенастрой A-записи на нём, а редирект включи уже для `skvortsovadv.ru`.

## Шаг 5. Подключить приём заявок (Telegram + Email)

Форма заявки шлёт данные на webhook. Пока webhook не задан — форма открывает
почтовый клиент (mailto) и предлагает Telegram, чтобы лиды не терялись.

Чтобы заявки автоматически падали в **Telegram и на Email**:

1. В своей n8n: **Workflows → Import from File** →
   [`site/n8n_lead_webhook.json`](../site/n8n_lead_webhook.json).
2. В ноде **Telegram уведомление**: подставь свои Telegram-креды и `chatId`
   (свой chat id можно узнать у бота [@userinfobot](https://t.me/userinfobot)).
3. В ноде **Email уведомление**: подставь SMTP-креды и `fromEmail`
   (toEmail уже `sunpavel@gmail.com`).
4. Активируй workflow, скопируй **Production URL** вебхука
   (вид `https://n8n.твой-домен.ru/webhook/lead`).
5. Впиши его в [`site/script.js`](../site/script.js) в строку
   `var LEAD_WEBHOOK_URL = "...";` и запушь — деплой произойдёт автоматически.

> Важно: n8n должна быть доступна по HTTPS и из России (на твоём VPS/домене).
> CORS в шаблоне уже открыт (`allowedOrigins: "*"`).

## Шаг 6. (Опционально) Старый домен Advskvortsov.com

Он сейчас указывает на Lovable (за Cloudflare → блок в РФ). Варианты:
- оставить как есть;
- сделать на нём 301-редирект на `https://skvortsovadv.ru` (через DNS-провайдера домена).

---

## Обновление контента

Просто редактируй файлы в `site/` (текст — в `index.html`) и пушь в `main` —
сайт пересоберётся сам за ~1 минуту.

## Проверка после запуска
- [ ] https://skvortsovadv.ru открывается (по HTTP и HTTPS)
- [ ] https://s-adv.ru редиректит на основной домен
- [ ] Форма отправляет заявку (приходит в Telegram и на почту)
- [ ] Добавь сайт в [Яндекс.Вебмастер](https://webmaster.yandex.ru/) и
      [Google Search Console](https://search.google.com/search-console),
      загрузи `sitemap.xml` — для индексации.
