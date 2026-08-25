#!/usr/bin/env python3
"""
send_campaign.py — рассылка по лидам с равномерным распределением между аккаунтами.

Запуск:
    python3 send_campaign.py <акки> [лимит] [пауза_мин] [пауза_макс]

<акки> — один или несколько через запятую: akk1  или  akk1,akk2,akk3
Сообщения расходятся по аккам по кругу (round-robin), каждый идёт через свой прокси.

Примеры:
    python3 send_campaign.py akk1 5
    python3 send_campaign.py akk1,akk2,akk3 9 40 120
"""

import os
import csv
import sys
import json
import time
import random
from datetime import datetime
from urllib.parse import urlparse

import openpyxl
from telethon.sync import TelegramClient

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def _load_creds():
    try:
        c = json.load(open("data/config.json", encoding="utf-8"))
        return int(c.get("api_id") or 0), c.get("api_hash") or ""
    except Exception:
        return 0, ""


API_ID, API_HASH = _load_creds()

SESSIONS = [s.strip() for s in (sys.argv[1] if len(sys.argv) > 1 else "akk3").split(",") if s.strip()]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 5
PAUSE_MIN = int(sys.argv[3]) if len(sys.argv) > 3 else 90
PAUSE_MAX = int(sys.argv[4]) if len(sys.argv) > 4 else 240
if PAUSE_MIN > PAUSE_MAX:
    PAUSE_MIN, PAUSE_MAX = PAUSE_MAX, PAUSE_MIN

LEADS = "data/leads.xlsx"
LOG = "data/sent_log.csv"
PROXIES = "data/proxies.json"
SENDING = "data/sending.json"   # кого сейчас шлём (для статуса «отправляется»)
NICK_COL = "ник"
MSG_COL = "сообщение для захода"
LOG_FIELDS = ["ник", "статус", "аккаунт", "время", "ошибка"]


def _parse_proxy(url):
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "socks5://" + url
    p = urlparse(url)
    if not p.hostname or not p.port:
        return None
    return {"proxy_type": p.scheme or "socks5", "addr": p.hostname, "port": p.port,
            "username": p.username or None, "password": p.password or None, "rdns": True}


def _get_proxy(name):
    if os.path.exists(PROXIES):
        try:
            return _parse_proxy(json.load(open(PROXIES, encoding="utf-8")).get(name))
        except Exception:
            return None
    return None


# постоянные ошибки — повторять бессмысленно (приватность, блок, нет юзера)
PERMANENT = ("privacy", "premium_required", "blocked", "banned", "restricted",
             "peer_id_invalid", "username_not_occupied", "username_invalid",
             "user_is_blocked", "deactivated")


def is_permanent(err):
    e = (err or "").lower()
    return any(k in e for k in PERMANENT)


def load_sent():
    """В done: успешно отправленные + ПОСТОЯННЫЕ ошибки.
    Временные ошибки (флуд, таймаут) НЕ в done — их повторим в следующий раз."""
    done = set()
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            st = r.get("статус")
            if st == "ok":
                done.add(r["ник"])
            elif st == "fail" and is_permanent(r.get("ошибка", "")):
                done.add(r["ник"])
    return done


def main():
    sent = load_sent()
    wb = openpyxl.load_workbook(LEADS)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in rows[0]]
    leads = [dict(zip(header, ["" if v is None else v for v in r])) for r in rows[1:]]
    todo = [r for r in leads
            if r.get(NICK_COL) and r[NICK_COL] not in sent and r.get(MSG_COL, "").strip()][:LIMIT]

    if not todo:
        print("Некому слать: всем отправлено или кончились лиды.")
        return

    # помечаем «в процессе» — дашборд покажет статус «отправляется»
    json.dump([r[NICK_COL] for r in todo], open(SENDING, "w", encoding="utf-8"), ensure_ascii=False)

    # открываем клиентов для каждого аккаунта (каждый через свой прокси)
    clients = {}
    for s in SESSIONS:
        try:
            c = TelegramClient(os.path.join("data", s), API_ID, API_HASH,
                               proxy=_get_proxy(s), flood_sleep_threshold=60)
            c.connect()
            if c.is_user_authorized():
                clients[s] = c
                print(f"  аккаунт {s}: готов")
            else:
                print(f"  аккаунт {s}: не авторизован, пропускаю")
                c.disconnect()
        except Exception as e:
            print(f"  аккаунт {s}: ошибка подключения ({e}), пропускаю")

    active = list(clients.keys())
    if not active:
        print("Нет ни одного рабочего аккаунта.")
        return

    print(f"\nРаспределяю {len(todo)} сообщений между {len(active)} акк(ами): {', '.join(active)}\n")

    new_log = not os.path.exists(LOG)
    logf = open(LOG, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
    if new_log:
        w.writeheader()
        logf.flush()

    for i, r in enumerate(todo):
        acc = active[i % len(active)]      # round-robin: равномерно по кругу
        client = clients[acc]
        nick = r[NICK_COL]
        text = r[MSG_COL].strip()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            ent = client.get_entity(nick)
            client.send_message(ent, text)
            print(f"[{i+1}/{len(todo)}] ✓ {nick}  ←  {acc}")
            w.writerow({"ник": nick, "статус": "ok", "аккаунт": acc, "время": ts, "ошибка": ""})
        except Exception as e:
            print(f"[{i+1}/{len(todo)}] ✗ {nick}  ←  {acc}: {e}")
            w.writerow({"ник": nick, "статус": "fail", "аккаунт": acc, "время": ts, "ошибка": str(e)})
            if "flood" in str(e).lower():
                print(f"    ⚠️ {acc} упёрся во флуд — убираю его из ротации.")
                active.remove(acc)
                if not active:
                    print("    Все аккаунты исчерпаны, останавливаюсь.")
                    logf.flush()
                    break
        logf.flush()
        if i < len(todo) - 1 and active:
            pause = random.randint(PAUSE_MIN, PAUSE_MAX)
            print(f"    пауза {pause} сек...")
            time.sleep(pause)

    for c in clients.values():
        try:
            c.disconnect()
        except Exception:
            pass
    logf.close()
    json.dump([], open(SENDING, "w", encoding="utf-8"))   # пачка закончена
    print(f"\nГотово. Лог: {LOG}")


if __name__ == "__main__":
    main()
