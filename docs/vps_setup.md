# Настройка VPS в РФ и запуск по расписанию

Зачем именно РФ-VPS: HH блокирует облачные/зарубежные IP (наш тест api.hh.ru → 403).
Резидентный российский IP нужен, чтобы боевой источник HH (эмуляция приложения) работал
стабильно.

## 🚀 Быстрый старт (одна команда)

На сервере, от root, после клонирования репозитория:

```bash
# 1) поставить git и склонировать (приватный репо → нужен GitHub PAT)
apt update && apt -y install git
git clone -b claude/eloquent-hopper-t3nrba https://<GITHUB_PAT>@github.com/sunpavel/findwork.git /opt/findwork
cd /opt/findwork

# 2) предварительно напиши любому сообщение боту в Telegram (чтобы определился chat_id)
# 3) запустить установщик (подставь токен бота)
TG_BOT_TOKEN='ТОКЕН_ОТ_BOTFATHER' bash deploy/setup.sh
```

Скрипт сам: поставит зависимости, определит chat_id, создаст `.env`, пришлёт тестовое
сообщение, настроит systemd-timer на 09:00 МСК. Ниже — то же самое вручную, по шагам.

## 1. Провайдер и сервер

Подойдёт минимальный VPS (1–2 vCPU, 1–2 ГБ RAM, Ubuntu 24.04). Провайдеры с РФ-локацией:
Timeweb, Selectel, REG.RU, Beget, VDSina. Тариф ~200–500 ₽/мес достаточно.

При заказе выбирай **локацию Москва/СПб** и ОС **Ubuntu 22.04/24.04**.

## 2. Базовая подготовка

```bash
ssh root@<ip-сервера>
apt update && apt -y upgrade
apt -y install python3 python3-venv python3-pip git
adduser --disabled-password --gecos "" findwork
su - findwork
```

## 3. Развернуть проект

```bash
git clone <URL-репозитория> findwork && cd findwork
python3 -m venv .venv && source .venv/bin/activate
# зависимостей у ядра нет; для боевого HH-источника понадобится:
pip install hh-applicant-tool
```

## 4. Секреты — в .env (не в git!)

```bash
cp .env.example .env
nano .env   # вписать TG_BOT_TOKEN, TG_CHAT_ID (см. docs/telegram_setup.md)
```

## 5. Проверить пайплайн на тестовых данных

```bash
set -a; source .env; set +a
python3 src/pipeline.py --source sample --dry-run     # без отправки
python3 src/pipeline.py --source sample --send        # пришлёт тестовый дайджест в Telegram
```

## 6. Авторизация в HH (для боевого источника)

```bash
hh-applicant-tool authorize     # один раз; откроет OAuth официального приложения HH
```

После этого можно реализовать/включить боевой источник: `python3 src/pipeline.py --source hh --send`.

> ⚠️ Это «серый» путь (эмуляция приложения, обход закрытого API). Риск — блокировка
> аккаунта HH. Поэтому: вежливые лимиты и паузы, отклики — только после подтверждения
> (выбран режим «полу-авто»). Не превращаем в спам.

## 7. Запуск каждое утро (systemd timer)

Создай `/etc/systemd/system/findwork.service`:

```ini
[Unit]
Description=findwork morning digest
After=network-online.target

[Service]
Type=oneshot
User=findwork
WorkingDirectory=/home/findwork/findwork
EnvironmentFile=/home/findwork/findwork/.env
ExecStart=/home/findwork/findwork/.venv/bin/python src/pipeline.py --source hh --send
```

И `/etc/systemd/system/findwork.timer`:

```ini
[Unit]
Description=Run findwork digest every morning

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Включить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now findwork.timer
systemctl list-timers findwork.timer   # проверить расписание
```

Готово — каждое утро в 09:00 по серверному времени придёт дайджест.
(Часовой пояс сервера: `timedatectl set-timezone Europe/Moscow`.)
