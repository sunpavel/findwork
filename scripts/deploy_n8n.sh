#!/usr/bin/env bash
# Перевыпуск n8n-воркфлоу дайджеста: HH (CCO/CMO) + facancy + Telegram-каналы,
# фильтр уже-откликнутых, вебхук приёма откликов. Секреты берутся из .env, id воркфлоу
# определяется автоматически по имени (дубликат не создаётся).
#
# Запуск:  bash scripts/deploy_n8n.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env"
[ -f "$ENV_FILE" ] || { echo "❌ нет $ENV_FILE (см. .env.example)"; exit 1; }

# Безопасная загрузка .env: НЕ через `source` (он исполняет значения как bash — а там есть
# скобки/пробелы, напр. HH_USER_AGENT=findwork/1.0 (sunpavel@gmail.com)). Парсим построчно
# и экспортируем литералы.
load_env() {
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"                      # CRLF → убрать \r
    case "$line" in ''|\#*) continue ;; esac  # пустые и комментарии
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="${key#export }"                       # терпим 'export KEY=...'
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    [ -z "$key" ] && continue
    case "$val" in                             # снять обрамляющие кавычки, если есть
      \"*\") val="${val#\"}"; val="${val%\"}" ;;
      \'*\') val="${val#\'}"; val="${val%\'}" ;;
    esac
    export "$key=$val"
  done < "$ENV_FILE"
}
load_env

PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
: "${N8N_URL:=https://solarn8n.pro}"
export N8N_URL

miss=()
[ -n "${N8N_KEY:-}" ]        || miss+=("N8N_KEY")
[ -n "${HH_CLIENT_ID:-}" ]    || miss+=("HH_CLIENT_ID")
[ -n "${HH_CLIENT_SECRET:-}" ] || miss+=("HH_CLIENT_SECRET")
if [ "${#miss[@]}" -gt 0 ]; then
  echo "❌ в .env не хватает: ${miss[*]}"
  echo "   добавь их в .env (см. .env.example) и повтори."
  exit 1
fi

echo "==> n8n: $N8N_URL · WF id: ${N8N_WF_ID:-авто по имени} · активация: ${N8N_ACTIVATE:-1}"
N8N_ACTIVATE="${N8N_ACTIVATE:-1}" "$PY" tools/build_n8n_workflow.py

echo
echo "Готово. Если бот ещё не шлёт историю откликов — проверь, что в .env есть:"
echo "  N8N_APPLIED_URL=${N8N_APPLIED_URL:-https://solarn8n.pro/webhook/findwork-applied}"
echo "и перезапусти бота:  sudo systemctl restart findwork-bot"
