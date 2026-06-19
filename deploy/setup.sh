#!/usr/bin/env bash
# Турнкей-установка findwork на VPS (Ubuntu). Запускать из корня репозитория от root:
#
#   TG_BOT_TOKEN='123:ABC' bash deploy/setup.sh
#
# TG_CHAT_ID можно не задавать — скрипт сам определит его из getUpdates,
# если ты уже написал что-нибудь боту. Иначе задай явно: TG_CHAT_ID='...'.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO_DIR/.venv/bin/python"
SOURCES="${SOURCES:-hh,tgchannels}"     # источники: hh (офиц. API) + публичные Telegram-каналы
DIGEST_TIME="${DIGEST_TIME:-09:00}"     # время утреннего дайджеста (по МСК)

echo "==> Репозиторий: $REPO_DIR"

if [[ -z "${TG_BOT_TOKEN:-}" ]]; then
  echo "ОШИБКА: задай TG_BOT_TOKEN. Пример: TG_BOT_TOKEN='123:ABC' bash deploy/setup.sh" >&2
  exit 1
fi

echo "==> Часовой пояс -> Europe/Moscow"
timedatectl set-timezone Europe/Moscow || true

echo "==> Системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null

echo "==> Виртуальное окружение"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
# Зависимостей нет — ядро и официальный HH-клиент на стандартной библиотеке.

# --- определить chat_id, если не задан ---
if [[ -z "${TG_CHAT_ID:-}" ]]; then
  echo "==> Определяю TG_CHAT_ID из getUpdates..."
  TG_CHAT_ID="$(curl -s "https://api.telegram.org/bot${TG_BOT_TOKEN}/getUpdates" \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
ids=[u.get("message",{}).get("chat",{}).get("id") for u in d.get("result",[])]
ids=[i for i in ids if i]
print(ids[-1] if ids else "")')"
  if [[ -z "$TG_CHAT_ID" ]]; then
    echo "ОШИБКА: не нашёл chat_id. Напиши любое сообщение боту в Telegram и запусти скрипт снова," >&2
    echo "       либо задай TG_CHAT_ID вручную." >&2
    exit 1
  fi
  echo "  Найден TG_CHAT_ID=$TG_CHAT_ID"
fi

echo "==> Пишу .env (секреты, права 600)"
cat > "$REPO_DIR/.env" <<EOF
TG_BOT_TOKEN=$TG_BOT_TOKEN
TG_CHAT_ID=$TG_CHAT_ID
EOF
chmod 600 "$REPO_DIR/.env"

echo "==> Тестовое сообщение в Telegram"
set -a; source "$REPO_DIR/.env"; set +a
"$PY" "$REPO_DIR/src/notify.py" "✅ findwork установлен на VPS. Утренний дайджест в ${DIGEST_TIME} МСК." || \
  echo "  (не отправилось — проверь токен/chat_id)"

echo "==> systemd service + timer"
cat > /etc/systemd/system/findwork.service <<EOF
[Unit]
Description=findwork morning digest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$PY $REPO_DIR/src/pipeline.py --source $SOURCES --send
EOF

cat > /etc/systemd/system/findwork.timer <<EOF
[Unit]
Description=Run findwork digest every morning

[Timer]
OnCalendar=*-*-* ${DIGEST_TIME}:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now findwork.timer

echo ""
echo "==> ГОТОВО."
echo "    • Тестовое сообщение должно было прийти в Telegram."
echo "    • Дайджест будет приходить каждый день в ${DIGEST_TIME} МСК (источники: $SOURCES)."
echo "    • Проверить таймер:   systemctl list-timers findwork.timer"
echo "    • Прогнать вручную:    set -a; source .env; set +a; $PY src/pipeline.py --source trudvsem --send"
echo ""
echo "    HH (официальный API): впиши в .env HH_CLIENT_ID/HH_CLIENT_SECRET/HH_REDIRECT_URI"
echo "    (регистрация приложения: https://dev.hh.ru/admin). Поиск заработает сразу."
echo "    Для откликов/персонального поиска — авторизация соискателя:"
echo "      set -a; source .env; set +a; $PY src/hh_auth.py url   (далее: ... code <CODE>)"
echo "    Подробности: docs/hh_api.md"
