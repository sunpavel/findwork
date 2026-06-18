#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# Установка findwork на сервере «под ключ»:
#   1) зависимости (pip-пакеты для PDF/DOCX + шрифт кириллицы);
#   2) прокси-клиент mihomo (Clash.Meta) из твоей VPN-подписки -> локальный
#      HTTP/SOCKS-прокси 127.0.0.1:7890 (обход гео-блока OpenAI/Anthropic);
#   3) LLM_PROXY в .env;
#   4) бот как сервис systemd (запуск 24/7, авто-рестарт).
#
# Использование (на сервере, под root):
#   bash scripts/setup.sh "<ССЫЛКА-ПОДПИСКА-VPN>"
#
# Пример:
#   bash scripts/setup.sh "https://join.example.store/iam/XXXX"
#
# Подписка НЕ сохраняется в репозиторий — она пишется только в /etc/mihomo на сервере.
# Повторный запуск безопасен (идемпотентно).

set -euo pipefail

SUB_URL="${1:-}"
PROXY_PORT="7890"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/.env"
PY="$(command -v python3)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "запускай под root (sudo)."
[ -n "$SUB_URL" ] || die "укажи ссылку-подписку VPN: bash scripts/setup.sh \"<URL>\""

# --- 1. Зависимости ----------------------------------------------------------
say "1/5 Зависимости (pip-пакеты для PDF/DOCX, шрифт кириллицы)"
apt-get update -qq
apt-get install -y -qq python3-pip fonts-dejavu-core curl gzip ca-certificates >/dev/null
"$PY" -m pip install --break-system-packages --quiet --upgrade fpdf2 python-docx >/dev/null
echo "ok: fpdf2, python-docx, fonts-dejavu-core"

# --- 2. mihomo (Clash.Meta) --------------------------------------------------
say "2/5 Прокси-клиент mihomo"
if ! command -v mihomo >/dev/null 2>&1; then
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) want="linux-amd64-compatible" ;;
    aarch64|arm64) want="linux-arm64" ;;
    *) die "неизвестная архитектура: $arch" ;;
  esac
  # Определяем свежий тег через редирект releases/latest (без GitHub API — он
  # часто отдаёт 403 по рейт-лимиту). Фолбэк — закреплённая версия.
  tag="$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
        https://github.com/MetaCubeX/mihomo/releases/latest 2>/dev/null | sed 's#.*/tag/##')"
  [ -n "$tag" ] || tag="v1.19.27"
  asset_url="https://github.com/MetaCubeX/mihomo/releases/download/${tag}/mihomo-${want}-${tag}.gz"
  say "  скачиваю mihomo ${tag} ($want)"
  curl -fsSL "$asset_url" -o /tmp/mihomo.gz || die "не скачался mihomo: $asset_url"
  gunzip -f /tmp/mihomo.gz
  install -m 0755 /tmp/mihomo /usr/local/bin/mihomo
  rm -f /tmp/mihomo
fi
echo "ok: $(mihomo -v 2>/dev/null | head -1 || echo mihomo)"

# --- 3. Конфиг mihomo из подписки + systemd ----------------------------------
say "3/5 Настройка mihomo из твоей подписки"
mkdir -p /etc/mihomo/providers
cat > /etc/mihomo/config.yaml <<YAML
mixed-port: ${PROXY_PORT}
allow-lan: false
mode: rule
log-level: warning
proxy-providers:
  vpn:
    type: http
    url: "${SUB_URL}"
    interval: 86400
    path: ./providers/vpn.yaml
    header:
      User-Agent: ["clash.meta", "mihomo"]
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300
proxy-groups:
  - name: PROXY
    type: url-test
    use: [vpn]
    url: https://www.gstatic.com/generate_204
    interval: 300
    tolerance: 50
rules:
  - MATCH,PROXY
YAML

cat > /etc/systemd/system/mihomo.service <<UNIT
[Unit]
Description=mihomo proxy (findwork)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now mihomo >/dev/null 2>&1 || systemctl restart mihomo
sleep 6

say "  проверяю выход через прокси…"
country="$(curl -s --max-time 25 -x "http://127.0.0.1:${PROXY_PORT}" https://ipinfo.io/country 2>/dev/null | tr -d '[:space:]' || true)"
if [ -z "$country" ]; then
  warn "прокси пока не отвечает. Логи: journalctl -u mihomo -n 50 --no-pager"
  warn "Часто помогает подождать минуту (подтягивается подписка) и перезапустить: systemctl restart mihomo"
elif [ "$country" = "RU" ]; then
  warn "прокси работает, но выходной IP всё ещё RU ($country) — OpenAI заблокирует."
  warn "Проверь, что в подписке есть зарубежные серверы."
else
  echo "ok: выход через прокси из страны: $country (не RU — гео-блок обойдён)"
fi

# --- 4. LLM_PROXY в .env -----------------------------------------------------
say "4/5 Прописываю LLM_PROXY в .env"
[ -f "$ENV_FILE" ] || die "нет $ENV_FILE — сначала создай .env (см. .env.example)."
grep -v '^LLM_PROXY=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
mv "$ENV_FILE.tmp" "$ENV_FILE"
echo "LLM_PROXY=http://127.0.0.1:${PROXY_PORT}" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "ok: LLM_PROXY=http://127.0.0.1:${PROXY_PORT}"

# --- 5. Бот как сервис systemd ----------------------------------------------
say "5/5 Бот как сервис systemd (24/7, авто-рестарт)"
cat > /etc/systemd/system/findwork-bot.service <<UNIT
[Unit]
Description=findwork Telegram bot
After=network-online.target mihomo.service
Wants=network-online.target

[Service]
WorkingDirectory=${REPO}
EnvironmentFile=${ENV_FILE}
ExecStart=${PY} ${REPO}/src/bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now findwork-bot >/dev/null 2>&1 || systemctl restart findwork-bot
sleep 2

say "Готово!"
cat <<DONE
Статус сервисов:
  systemctl status mihomo --no-pager
  systemctl status findwork-bot --no-pager
Логи бота вживую:
  journalctl -u findwork-bot -f
Обновить проект потом:
  cd ${REPO} && git pull && systemctl restart findwork-bot

В Telegram отправь боту /health — строка «Письма (LLM)» должна стать зелёной.
DONE
