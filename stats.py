#!/usr/bin/env python3
"""stats.py — reply-rate по аккаунтам и по базам.

Считает ТОЛЬКО на чтение, схему логов не меняет:
  data/sent_log.csv   — полный журнал: кто и с какого акка отправил (ok/fail)
  data/replies.json   — кто ответил (ник -> {когда, аккаунт, текст})
  data/bases.json     — принадлежность ников к базам: {"база": ["ник", ...]}

Разбивка «по базе» = по членству ника в списке базы (bases.json), а НЕ по
ключевым словам в тексте — так не мешаются базы между собой.
Добавляешь новую базу — дописываешь её в bases.json, и всё считается само.

reply-rate = ответивших / отправлено. Малые числа статистически шумные —
поэтому рядом с процентом всегда сырые (ответов/отправлено).
"""

import os
import csv
import json
import datetime
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LOG = "data/sent_log.csv"
REPLIES = "data/replies.json"
BASES = "data/bases.json"
FOLLOWUPS = "data/followups.json"
FTEXT = "data/followups_text.json"
OTHER = "прочее"   # ник не найден ни в одной базе (ручные отправки и т.п.)
FU_DAY2, FU_DAY3 = 3, 7   # держать в синхроне с followup.py


def _key(n):
    """Единый вид ника для сопоставления: без @, нижний регистр."""
    return str(n or "").lstrip("@").strip().lower()


def _load_replies():
    try:
        return json.load(open(REPLIES, encoding="utf-8"))
    except Exception:
        return {}


def _load_bases():
    """(порядок_имён, {ник_key -> база})."""
    try:
        b = json.load(open(BASES, encoding="utf-8"))
    except Exception:
        return [], {}
    order, m = [], {}
    for name, nicks in b.items():
        order.append(name)
        for n in nicks:
            m[_key(n)] = name
    return order, m


def _sent_ok():
    """[(ник, аккаунт)] по всем успешным отправкам из полного журнала."""
    out = []
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            if r.get("статус") == "ok":
                out.append((r.get("ник", ""), r.get("аккаунт", "")))
    return out


def per_account():
    """[(acc, sent_ok, replies, rate%)] — по убыванию отклика, затем объёма."""
    sent = defaultdict(int)
    for nick, acc in _sent_ok():
        if acc:
            sent[acc] += 1
    rep = defaultdict(int)
    for v in _load_replies().values():
        if isinstance(v, dict) and v.get("аккаунт"):
            rep[v["аккаунт"]] += 1
    out = []
    for acc, s in sent.items():
        rr = rep.get(acc, 0)
        out.append((acc, s, rr, round(100 * rr / s, 1) if s else 0.0))
    out.sort(key=lambda x: (-x[3], -x[1]))
    return out


def per_base():
    """[(база, sent_ok, replies, rate%)] — по убыванию объёма.
    Классифицируем ник по членству в bases.json."""
    order, m = _load_bases()

    sent = defaultdict(int)
    for nick, _ in _sent_ok():
        sent[m.get(_key(nick), OTHER)] += 1
    rep = defaultdict(int)
    for nick in _load_replies():
        rep[m.get(_key(nick), OTHER)] += 1

    names = order + [OTHER]
    seen = set()
    out = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        s = sent.get(name, 0)
        if not s:
            continue
        rr = rep.get(name, 0)
        out.append((name, s, rr, round(100 * rr / s, 1) if s else 0.0))
    out.sort(key=lambda x: -x[1])
    return out


def summary_text():
    """Компактный блок для Telegram-отчёта."""
    pb, pa = per_base(), per_account()
    m = ""
    if pb:
        m += "\n📇 Отклик по базе (за всё время):\n"
        for name, s, rr, rate in pb:
            m += f"  · {name}: {rate}% ({rr}/{s})\n"
    if pa:
        m += "\n👤 Отклик по акку (за всё время):\n"
        for acc, s, rr, rate in pa:
            m += f"  · {acc}: {rate}% ({rr}/{s})\n"
    return m


# ─────────────── фоллоапы: тексты и аналитика ───────────────
def followups_text_load():
    try:
        return json.load(open(FTEXT, encoding="utf-8"))
    except Exception:
        return {}


def followups_text_save(d):
    json.dump(d, open(FTEXT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def followup_bases():
    """Базы для редактора текстов: из bases.json + 'default'."""
    order, _ = _load_bases()
    return order + ["default"]


def _followups_state():
    try:
        return json.load(open(FOLLOWUPS, encoding="utf-8"))
    except Exception:
        return {}


def _first_ts():
    firsts = {}
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            n = r.get("ник")
            if r.get("статус") == "ok" and n and n not in firsts:
                firsts[n] = r.get("время", "")
    return firsts


def _age(ts):
    try:
        dt = datetime.datetime.strptime(str(ts)[:16], "%Y-%m-%d %H:%M")
        return (datetime.datetime.utcnow() - dt).days
    except Exception:
        return -1


def followup_overview():
    """[(база, первое, ответили, ждут_добивки, касание2, касание3, ответили_после)] по объёму."""
    order, m = _load_bases()
    firsts = _first_ts()
    reps = set(_key(k) for k in _load_replies())
    state = _followups_state()

    blank = lambda: {"first": 0, "replied": 0, "due": 0, "s2": 0, "s3": 0, "after": 0}
    agg = defaultdict(blank)
    for nick, ts in firsts.items():
        base = m.get(_key(nick), OTHER)
        a = agg[base]
        a["first"] += 1
        replied = _key(nick) in reps
        if replied:
            a["replied"] += 1
        stg = state.get(nick, {}).get("stage", 0)
        if stg >= 2:
            a["s2"] += 1
            if replied:
                a["after"] += 1
        if stg >= 3:
            a["s3"] += 1
        if (not replied) and stg < 3 and _age(ts) >= FU_DAY2:
            a["due"] += 1

    names = order + [OTHER]
    out = []
    for n in names:
        a = agg.get(n)
        if not a or a["first"] == 0:
            continue
        out.append((n, a["first"], a["replied"], a["due"], a["s2"], a["s3"], a["after"]))
    out.sort(key=lambda x: -x[1])
    return out


if __name__ == "__main__":
    print(summary_text())
