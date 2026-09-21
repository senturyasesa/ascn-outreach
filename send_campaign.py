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
from datetime import datetime
from urllib.parse import urlparse

import openpyxl

import tg
import campaign as C
import alerts
from errors_map import cell_text, err_code, is_account_dead, is_permanent

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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
INVALID = "data/invalid.json"   # ники, которых не существует (проверка базы)
SENT_TEXT = "data/sent_text.csv" # что именно ушло — чтобы считать reply rate по текстам
NICK_COL = "ник"
MSG_COL = "сообщение для захода"
try:
    _BROADCAST = open("data/broadcast.txt", encoding="utf-8").read().strip()
except Exception:
    _BROADCAST = ""
LOG_FIELDS = ["ник", "статус", "аккаунт", "время", "ошибка"]


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


def _log_text(nick, acc, ts, text, choices):
    """Что именно ушло человеку и какие варианты выпали.
    Отдельным файлом, чтобы не менять схему sent_log.csv."""
    new = not os.path.exists(SENT_TEXT)
    with open(SENT_TEXT, "a", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=["ник", "аккаунт", "время", "вариант", "текст"])
        if new:
            wr.writeheader()
        wr.writerow({"ник": nick, "аккаунт": acc, "время": ts,
                     "вариант": " | ".join(choices), "текст": text})


def main():
    sent = load_sent()
    wb = openpyxl.load_workbook(LEADS)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in rows[0]]
    leads = [dict(zip(header, ["" if v is None else v for v in r])) for r in rows[1:]]
    for r in leads:                       # ячейка может быть числом/датой — приводим к строке
        r[NICK_COL] = cell_text(r.get(NICK_COL))
        r[MSG_COL] = cell_text(r.get(MSG_COL))
    invalid = set()
    if os.path.exists(INVALID):
        try:
            invalid = set(json.load(open(INVALID, encoding="utf-8")))
        except Exception:
            invalid = set()
    queue = [r for r in leads
             if r[NICK_COL] and r[NICK_COL] not in sent and r[NICK_COL] not in invalid
             and (_BROADCAST or r[MSG_COL])]
    if invalid:
        print(f"  пропускаю {len(invalid)} мёртвых ников (проверка базы)")
    if not queue:
        print("Некому слать: всем отправлено или кончились лиды.")
        return

    # дневная ёмкость: сколько ещё можно отправить с каждого аккаунта сегодня
    limits = C.load_limits()
    today = C.sent_today()
    left = {a: C.remaining(a, limits, today) for a in SESSIONS}
    for a in SESSIONS:
        used, cap = today.get(a, 0), C.daily_cap(a, limits)
        print(f"  {a}: сегодня {used} из {cap}, осталось {left[a]}")
    room = sum(left.values())
    if room <= 0:
        print("\nДневной лимит выбран по всем аккаунтам. Продолжим завтра — "
              "это и есть защита от бана.")
        return
    if room < LIMIT:
        print(f"\nПрошу {LIMIT}, но на сегодня осталось {room} — отправлю {room}.")
    todo = queue[:min(LIMIT, room)]

    # помечаем «в процессе» — дашборд покажет статус «отправляется»
    json.dump([r[NICK_COL] for r in todo], open(SENDING, "w", encoding="utf-8"), ensure_ascii=False)

    # клиентов открывает tg.py: ключи, прокси, профиль устройства
    clients = tg.open_clients(SESSIONS)

    active = [a for a in clients if left.get(a, 0) > 0]
    if not active:
        print("Нет ни одного аккаунта с запасом на сегодня.")
        return

    print(f"\nРаспределяю {len(todo)} сообщений между {len(active)} акк(ами): {', '.join(active)}\n")

    new_log = not os.path.exists(LOG)
    logf = open(LOG, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
    if new_log:
        w.writeheader()
        logf.flush()

    turn = [0]   # указатель round-robin; аккаунты без остатка пропускаем

    def next_account():
        for _ in range(len(active)):
            acc = active[turn[0] % len(active)]
            turn[0] += 1
            if left.get(acc, 0) > 0:
                return acc
        return None

    for i, r in enumerate(todo):
        acc = next_account()
        if acc is None:
            print("    Дневные лимиты выбраны, останавливаюсь. Остальные — в очереди.")
            break
        client = clients[acc]
        nick = r[NICK_COL]
        text, choices = C.render_message(_BROADCAST or r[MSG_COL], r, return_choices=True)
        text = C.rewrite(text, broadcast=bool(_BROADCAST))   # AI-уникализация + чистка тире
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        left[acc] -= 1
        try:
            ent = client.get_entity(nick)
            with client.action(ent, "typing"):    # как живой: сначала «печатает»
                time.sleep(C.typing_seconds(text))
                client.send_message(ent, text)
            print(f"[{i+1}/{len(todo)}] ✓ {nick}  ←  {acc}")
            w.writerow({"ник": nick, "статус": "ok", "аккаунт": acc, "время": ts, "ошибка": ""})
            _log_text(nick, acc, ts, text, choices)
        except Exception as e:
            print(f"[{i+1}/{len(todo)}] ✗ {nick}  ←  {acc}: {e}")
            w.writerow({"ник": nick, "статус": "fail", "аккаунт": acc, "время": ts,
                        "ошибка": err_code(e)})
            if alerts.is_flood(e):
                alerts.alert_flood(acc, e)
            if is_account_dead(e):
                print(f"    ⚠️ {acc}: {type(e).__name__} — убираю аккаунт из ротации. "
                      f"{nick} вернётся в очередь.")
                active.remove(acc)
                if not active:
                    print("    Все аккаунты исчерпаны, останавливаюсь.")
                    logf.flush()
                    break
        logf.flush()
        if i < len(todo) - 1 and active:
            pause = C.pause_seconds(PAUSE_MIN, PAUSE_MAX)
            print(f"    пауза {pause} сек...")
            time.sleep(pause)

    tg.close_clients(clients)
    logf.close()
    json.dump([], open(SENDING, "w", encoding="utf-8"))   # пачка закончена
    print(f"\nГотово. Лог: {LOG}")


if __name__ == "__main__":
    main()
