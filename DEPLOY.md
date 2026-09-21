# DEPLOY — развёртывание на сервере

Автоматическая установка инфраструктуры одной командой. «Расходники» (аккаунты,
api-ключи, прокси, база, текст) заполняются вручную — их автоматом создать нельзя.

---

## Требования к серверу

- Linux с `apt` (Ubuntu/Debian) или `dnf` — `deploy.sh` сам доставит `python3`,
  `python3-venv`, `pip`, `git`. На других дистрибутивах поставь их вручную.
- Python 3.9–3.12 (на 3.13 для аккаунтов может понадобиться патч opentele).
- Доступ `sudo` (для регистрации systemd-юнитов).
- Открытый порт **8765** для дашборда (`sudo ufw allow 8765/tcp` или firewall провайдера).

## Быстрый старт

```bash
# 1. Забрать код
git clone git@github.com:senturyasesa/ascn-outreach.git
cd ascn-outreach

# 2. Развернуть инфраструктуру (venv, зависимости, папки, systemd-юниты)
sudo ./deploy/deploy.sh
```

`deploy.sh` сделает автоматически:
- Python venv + все зависимости (+ `opentele` для аккаунтов)
- папки `data/` и `backups/`
- заготовки конфигов из `.example` (не перезаписывает существующие)
- зарегистрирует systemd-юниты (подставит реальный путь установки)

---

## Что заполнить самому (твои данные)

| # | Файл | Что | Где взять |
|---|---|---|---|
| 1 | `data/config.json` | api_id / api_hash | https://my.telegram.org |
| 2 | `.env` | TG_BOT_TOKEN / TG_CHAT_ID | бот у @BotFather + id твоей группы |
| 3 | `data/proxies.json` | SOCKS5 на аккаунт | твой провайдер прокси |
| 4 | `data/leads.xlsx` | база лидов | образец `data/leads.example.xlsx` |
| 5 | `data/broadcast.txt` | текст рассылки | пишешь сам |
| 6 | **аккаунты** (`.session`) | авторизации Telegram | **через tdata — [ONBOARDING.md](ONBOARDING.md) раздел 2** |

> Пункт 6 (аккаунты) — единственное, что остаётся ручной работой всегда:
> Telegram не даёт логинить аккаунты по коду для рассылки, только через tdata.

---

## Запуск сервисов

После заполнения данных:

```bash
sudo systemctl enable --now ascn-outreach ascn-daily ascn-notify.timer ascn-report.timer
```

| Сервис | Что делает |
|---|---|
| `ascn-outreach` | веб-дашборд (порт 8765) |
| `ascn-daily` | демон дневной рассылки |
| `ascn-notify.timer` | проверка ответов каждые 15 мин |
| `ascn-report.timer` | почасовые отчёты в бота (09-21 МСК) |

Дашборд: `http://<IP-сервера>:8765`

---

## Проверка и управление

```bash
systemctl status ascn-outreach          # статус
journalctl -u ascn-daily -f             # логи демона рассылки
systemctl list-timers | grep ascn       # расписание таймеров
systemctl restart ascn-outreach         # перезапуск дашборда
```

---

## Обновление кода (существующая установка)

Данные не трогаются (они в `.gitignore`), обновляется только код:

```bash
cd ascn-outreach
git pull
./venv/bin/pip install -r requirements.txt   # если менялись зависимости
sudo systemctl restart ascn-outreach ascn-daily
```

---

## Итого поток развёртывания

```
git clone → sudo ./deploy/deploy.sh → заполнить свои данные → systemctl enable --now …
```

Всё, кроме аккаунтов (tdata) и твоих ключей/базы — автоматизировано.
Детали по аккаунтам и эксплуатации — в **[ONBOARDING.md](ONBOARDING.md)**.
