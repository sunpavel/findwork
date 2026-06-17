# Быстрый старт findwork

Одно место со всеми шагами: от нуля до работающего бота. Делается **на твоём
компьютере или VPS** — не в облачной среде Claude (она временная и гаснет).

> Telegram и facancy.ru работают сразу. Отклики на HH включаются после шага 2
> (это «серый» путь — эмуляция приложения HH, риск блокировки аккаунта; см.
> [auto_apply.md](auto_apply.md)).

---

## 0. Скачать проект и зависимости

```bash
git clone <repo> findwork && cd findwork
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # нужно для LLM-писем (пакет anthropic)
```

## 1. Telegram-бот

Бот уже создан — `@vacancyparse_bot`. Нужны две вещи в `.env` (шаг 3):

- **TG_BOT_TOKEN** — токен от @BotFather (если потеряешь — `/revoke` в @BotFather).
- **TG_CHAT_ID** — твой numeric id. Узнать: напиши боту любое сообщение и открой
  `https://api.telegram.org/bot<ТОКЕН>/getUpdates` → поле `"chat":{"id":...}`.

Подробно — [telegram_setup.md](telegram_setup.md).

## 2. Авторизация HH (один раз) — для откликов

Официальный dev-токен HH умеет только искать вакансии; создавать резюме и слать
отклики он запрещает (403). Нужен токен **мобильного приложения** HH:

```bash
pipx install hh-applicant-tool        # или: pip install hh-applicant-tool
hh-applicant-tool authorize           # откроется браузер → войди в свой HH-аккаунт → разреши
```

Токен сохранится в `~/.config/hh-applicant-tool/`, и `src/hh_app.py` подхватит его
автоматически. Проверка:

```bash
python3 src/hh_app.py
# OK — авторизован как: Павел … + список твоих резюме
```

> Только ты можешь сделать этот шаг — он требует входа в твой HH-аккаунт через браузер.
> Альтернатива без инструмента: положить готовый токен в `HH_APP_ACCESS_TOKEN` (см. `.env.example`).

## 3. Файл `.env`

Скопируй `.env.example` → `.env` и заполни (файл в `.gitignore`, в репозиторий не попадёт):

```ini
TG_BOT_TOKEN=...            # от @BotFather
TG_CHAT_ID=...              # твой chat_id
ANTHROPIC_API_KEY=...       # для качественных писем; без него — шаблон
APPLY_DAILY_LIMIT=30        # вежливый лимит откликов в день
# APPLY_RESUME_MODE=clone   # clone (новое резюме под вакансию) | update | existing
# HH_BASE_RESUME_ID=...     # базовое резюме (по умолчанию — первое из твоих)
```

## 4. Запуск бота

```bash
set -a && source .env && set +a       # подгрузить переменные окружения
python3 src/bot.py
```

В Telegram отправь боту `/health` — он покажет, что подключено
(Telegram ✅ / Anthropic / HH). Дальше:

- **ссылка на вакансию HH** → бот пришлёт резюме и письмо и кнопку «✅ Откликнуться»
  (отклик уйдёт только после нажатия);
- **ссылка facancy.ru** (или другой сайт) → бот пришлёт резюме и письмо, отклик делаешь сам.

Команды: `/health`, `/status`, `/pause`, `/resume`, `/dry <ссылка>`, `/help`.

## 5. Чтобы работало постоянно (VPS)

Бот — долгоживущий процесс, держи его на VPS под `systemd`. Готовый гайд —
[vps_setup.md](vps_setup.md).

---

## Безопасность

- Секреты — только в `.env` (он в `.gitignore`). Никогда не коммить токены.
- Если токен/ключ где-то засветился — перевыпусти: бот в @BotFather (`/revoke`),
  ключ Anthropic в console.anthropic.com, HH — повторный `hh-applicant-tool authorize`.
- HH-отклики — «серый» путь. Снижают риск: подтверждение кнопкой, `/pause`,
  дневной лимит, паузы, анти-дубль, точечность (только присланная вакансия).
