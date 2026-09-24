#!/usr/bin/env python3
"""followup.py — авто-фоллоапы: лид не ответил за N дней -> второе/третье касание.

Запуск раз в день таймером ascn-followup.timer. Шлёт с того же аккаунта, что писал
первым, через копию сессии (без конфликта с демоном рассылки), с AI-рерайтом для
уникальности. НЕ трогает: ответивших, мёртвых ников, платных (постоянная ошибка),
замороженные/чёрные/выбывшие аккаунты. Идёт мягко, с паузами и предохранителем.

Тексты касаний — в data/followup2.txt (день 3) и data/followup3.txt (день 7).
Прогресс по каждому лиду — data/followups.json {ник: {stage, last}}.
"""

import os
import csv
import json
import time
import random
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import tg
import campaign as C
import spambot
import alerts
from errors_map import is_permanent

LOG = "data/sent_log.csv"
REPLIES = "data/replies.json"
STATE = "data/followups.json"
ACCOUNTS = "data/accounts.json"
BLACKLIST = "data/blacklist.json"
F2 = "data/followup2.txt"
F3 = "data/followup3.txt"

DAY2 = 3          # дней после первого касания -> фоллоап №2
DAY3 = 7          # дней после первого касания -> фоллоап №3
MAX_PER_RUN = 25  # предохранитель на весь прогон
ACC_CAP = 4       # не больше стольких фоллоапов на один аккаунт за прогон (антифлуд)
PAUSE = (20, 60)  # пауза между отправками, сек


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _read(p):
    try:
        return open(p, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _days_ago(ts):
    try:
        dt = datetime.datetime.strptime(str(ts)[:16], "%Y-%m-%d %H:%M")
        return (datetime.datetime.utcnow() - dt).days
    except Exception:
        return -1


def _is_flood(err):
    e = str(err or "").lower()
    return any(k in e for k in ("flood", "too many", "peerflood", "slowmode"))


def _first_sends():
    """ник -> (acc, ts) по ПЕРВОЙ успешной отправке; + множество ников с постоянной ошибкой."""
    firsts, permfail = {}, set()
    for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
        nick, st = r.get("ник"), r.get("статус")
        if st == "ok" and nick and nick not in firsts:
            firsts[nick] = (r.get("аккаунт", ""), r.get("время", ""))
        elif st == "fail" and is_permanent(r.get("ошибка", "")):
            permfail.add(nick)
    return firsts, permfail


def main(dry=False):
    if not os.path.exists(LOG):
        print("нет sent_log")
        return
    if not dry:
        spambot.thaw_expired()

    firsts, permfail = _first_sends()
    replies = set(_load(REPLIES, {}).keys())
    invalid = set(C.load_invalid().keys()) if isinstance(C.load_invalid(), dict) else set()
    accounts = set(_load(ACCOUNTS, []))
    bl = set(_load(BLACKLIST, {}).keys())
    state = _load(STATE, {})
    f2, f3 = _read(F2), _read(F3)

    order = list(firsts.items())
    random.shuffle(order)
    sent = c2 = c3 = 0
    per_acc = {}   # антифлуд: сколько фоллоапов ушло с каждого акка за прогон

    for nick, (acc, ts) in order:
        if sent >= MAX_PER_RUN:
            break
        if nick in replies or nick in invalid or nick in permfail:
            continue
        if not acc or (accounts and acc not in accounts) or acc in bl or spambot.is_frozen(acc):
            continue
        if per_acc.get(acc, 0) >= ACC_CAP:
            continue

        age = _days_ago(ts)
        st = state.get(nick, {})
        stage = st.get("stage", 0)
        text = newstage = None

        if stage == 0 and age >= DAY2 and f2:
            text, newstage = f2, 2
        elif stage == 2 and f3:
            since_last = _days_ago(st.get("last", ts))
            if age >= DAY3 and since_last >= (DAY3 - DAY2):
                text, newstage = f3, 3
        if not text:
            continue

        if dry:
            sent += 1
            c2 += newstage == 2
            c3 += newstage == 3
            per_acc[acc] = per_acc.get(acc, 0) + 1
            print(f"[dry] {nick} (акк {acc}, {age}д) -> касание №{'2' if newstage == 2 else '3'}")
            continue

        msg = C.rewrite(text, broadcast=True)   # уникализация (если рерайт включён)
        ok, err = tg.send_reply(acc, nick, msg)
        if ok:
            state[nick] = {"stage": newstage,
                           "last": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
            sent += 1
            c2 += newstage == 2
            c3 += newstage == 3
            per_acc[acc] = per_acc.get(acc, 0) + 1
            time.sleep(random.uniform(*PAUSE))
        elif _is_flood(err):
            spambot.enqueue(acc)
            alerts.alert_flood(acc, Exception(str(err)))
        # прочие ошибки: не помечаем, попробуем в следующий прогон

    if dry:
        print(f"[dry] всего под фоллоап: {sent} (день3={c2}, день7={c3}). Ничего не отправлено.")
        return
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if sent:
        alerts.alert(f"📨 Авто-фоллоапы: отправлено {sent} (день3: {c2}, день7: {c3}).")
    print(f"followups sent: {sent} (день3={c2}, день7={c3})")


if __name__ == "__main__":
    import sys
    main(dry="--dry" in sys.argv)
