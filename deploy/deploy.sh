#!/usr/bin/env bash
# ASCN Outreach — автоматическое развёртывание инфраструктуры.
# Ставит venv+зависимости, создаёт папки/заготовки конфигов, регистрирует systemd-юниты.
# ЧТО НЕ ДЕЛАЕТ (это твои данные — заполняешь сам): api-ключи, аккаунты, прокси, база, текст.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
echo "==> Каталог приложения: $APP_DIR"

echo "==> Проверка/установка системных зависимостей"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip git
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y -q python3 python3-pip git
else
  echo "    ⚠ не apt/dnf — поставь вручную: python3, python3-venv, python3-pip, git"
fi

PYV=$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Python $PYV"
case "$PYV" in
  3.9|3.10|3.11|3.12) : ;;
  *) echo "    ⚠ Python $PYV: для добавления аккаунтов через tdata может понадобиться патч opentele (см. ONBOARDING.md 2.3)";;
esac

echo "==> Python venv + зависимости"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
./venv/bin/pip install --quiet opentele   # для добавления аккаунтов через tdata

echo "==> Папки и заготовки конфигов (не перезаписываю существующие)"
mkdir -p data backups
[ -f .env ]                || cp .env.example .env
[ -f data/config.json ]    || cp data/config.example.json data/config.json
[ -f data/proxies.json ]   || cp data/proxies.example.json data/proxies.json
[ -f data/rewrite.json ]   || cp data/rewrite.example.json data/rewrite.json
[ -f data/broadcast.txt ]  || : > data/broadcast.txt
[ -f data/accounts.json ]  || echo "[]" > data/accounts.json
[ -f data/limits.json ]    || echo '{"default": 10}' > data/limits.json

echo "==> Регистрация systemd-юнитов"
for f in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed "s|__APP_DIR__|$APP_DIR|g" "$f" | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
  echo "    установлен $(basename "$f")"
done
sudo systemctl daemon-reload

cat <<MSG

✅ Инфраструктура развёрнута.

ДАЛЬШЕ — заполни СВОИ данные (это твои расходы/решения, автоматом не сделать):
  1. data/config.json    — api_id / api_hash  (получить на my.telegram.org)
  2. .env                — TG_BOT_TOKEN / TG_CHAT_ID  (бот у @BotFather + id группы)
  3. data/proxies.json   — SOCKS5-прокси на аккаунт
  4. data/leads.xlsx     — база лидов
  5. data/broadcast.txt  — текст рассылки
  6. АККАУНТЫ через tdata — см. ONBOARDING.md, раздел 2 (самое важное)

  7. data/ai_sales_prompt.txt + data/ai_sales_kb.md — промпт и база ИИ-продажника
                           (образцы: *.example.txt / *.example.md; ключ OpenRouter из rewrite.json)

Затем включи сервисы:
  sudo systemctl enable --now ascn-outreach ascn-daily ascn-notify.timer ascn-report.timer ascn-bot

Проверка:
  systemctl status ascn-outreach
  дашборд → http://<IP-сервера>:8765

  Если дашборд недоступен снаружи — открой порт:
    sudo ufw allow 8765/tcp    (или проверь firewall провайдера)
MSG
