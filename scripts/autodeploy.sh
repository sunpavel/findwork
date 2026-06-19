#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Авто-деплой findwork: подтягивает изменения текущей ветки из origin и, если они
# есть, перезапускает бота. Ставится как systemd-таймер (раз в минуту) скриптом
# scripts/setup.sh — после этого правки деплоятся сами, без ручных команд.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$BRANCH" || exit 0   # нет сети — тихо выходим, таймер повторит

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
[ "$LOCAL" = "$REMOTE" ] && exit 0             # нечего деплоить

git merge --ff-only "origin/$BRANCH"

# Обновились pip-зависимости — доставим (без шума), иначе бот может не подняться.
if git diff --name-only "$LOCAL" "$REMOTE" | grep -q '^requirements\.txt$'; then
  python3 -m pip install --break-system-packages --quiet -r requirements.txt || true
fi

systemctl restart findwork-bot
logger -t findwork-deploy "deployed ${REMOTE} on ${BRANCH}"
