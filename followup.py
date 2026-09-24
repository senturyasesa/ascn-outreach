#!/usr/bin/env python3
"""followup.py — авто-фоллоапы: лид не ответил за N дней -> второе/третье касание.

Тексты касаний — СВОИ под каждую базу (data/followups_text.json), потому что у
разных баз разный первый заход. Если у базы текста нет, берётся "default".

Запуск раз в день таймером ascn-followup.timer. Шлёт с того же аккаунта, что писал
первым, через копию сессии (без конфликта с демоном), с AI-рерайтом. НЕ трогает:
ответивших, мёртвых ников, платных (постоянная ошибка), замороженные/чёрные/выбывшие
аккаунты. Кап на аккаунт + общий кап (антифлуд), паузы. Режим --dry ничего не шлёт.

Прогресс по лидам — data/followups.json {ник: {stage, last, base}}.
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
import ai_sales
from errors_map import is_permanent

LOG = "data/sent_log.csv"
REPLIES = "data/replies.json"
STATE = "data/followups.json"
ACCOUNTS = "data/accounts.json"
BLACKLIST = "data/blacklist.json"
BASES = "data/bases.json"
FTEXT = "data/followups_text.json"   # {база: {"2": текст, "3": текст}, "default": {...}}

DAY2 = 3          # дней после первого касания -> фоллоап №2
DAY3 = 7          # дней после первого касания -> фоллоап №3
MAX_PER_RUN = 25  # предохранитель на весь прогон
ACC_CAP = 4       # не больше стольких фоллоапов на один аккаунт за прогон (антифлуд)
PAUSE = (20, 60)  # пауза между отправками, сек
DEFAULT = "default"


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _key(n):
    return str(n or "").lstrip("@").strip().lower()


def _basemap():
    m = {}
    for base, nicks in _load(BASES, {}).items():
        for n in nicks:
            m[_key(n)] = base
    return m


def _choose(ft, base, stage, cache):
    """Текст касания. Приоритет: явный текст под базу -> ИИ сам пишет -> запасной default.
    ИИ-текст генерится один раз на (база, стадия) за прогон и кэшируется."""
    s = str(stage)
    bt = ((ft.get(base) or {}).get(s) or "").strip()   # 1. вручную под базу
    if bt:
        return bt
    ck = (base, stage)                                  # 2. ИИ сам
    if ck not in cache:
        cache[ck] = ai_sales.generate_followup(stage, base) or ""
    if cache[ck]:
        return cache[ck]
    return ((ft.get(DEFAULT) or {}).get(s) or "").strip()  # 3. запасной


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
    """ник -> (acc, ts) по ПЕРВОЙ успешной отправке; + ники с постоянной ошибкой."""
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
    ft = _load(FTEXT, {})
    basemap = _basemap()

    order = list(firsts.items())
    random.shuffle(order)
    sent = c2 = c3 = 0
    per_acc = {}
    auto = {}   # кэш ИИ-текстов на прогон: (база, стадия) -> текст

    for nick, (acc, ts) in order:
        if sent >= MAX_PER_RUN:
            break
        if nick in replies or nick in invalid or nick in permfail:
            continue
        if not acc or (accounts and acc not in accounts) or acc in bl or spambot.is_frozen(acc):
            continue
        if per_acc.get(acc, 0) >= ACC_CAP:
            continue

        base = basemap.get(_key(nick), DEFAULT)
        age = _days_ago(ts)
        st = state.get(nick, {})
        stage = st.get("stage", 0)
        text = newstage = None

        if stage == 0 and age >= DAY2:
            t = _choose(ft, base, 2, auto)
            if t:
                text, newstage = t, 2
        elif stage == 2:
            since_last = _days_ago(st.get("last", ts))
            if age >= DAY3 and since_last >= (DAY3 - DAY2):
                t = _choose(ft, base, 3, auto)
                if t:
                    text, newstage = t, 3
        if not text:
            continue

        if dry:
            sent += 1
            c2 += newstage == 2
            c3 += newstage == 3
            per_acc[acc] = per_acc.get(acc, 0) + 1
            print(f"[dry] {nick} [{base}] №{newstage}: {text[:70]}")
            continue

        msg = C.rewrite(text, broadcast=True)   # уникализация (если рерайт включён)
        ok, err = tg.send_reply(acc, nick, msg)
        if ok:
            state[nick] = {"stage": newstage, "base": base,
                           "last": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")}
            sent += 1
            c2 += newstage == 2
            c3 += newstage == 3
            per_acc[acc] = per_acc.get(acc, 0) + 1
            time.sleep(random.uniform(*PAUSE))
        elif _is_flood(err):
            spambot.enqueue(acc)
            alerts.alert_flood(acc, Exception(str(err)))

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
