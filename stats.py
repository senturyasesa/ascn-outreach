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
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LOG = "data/sent_log.csv"
REPLIES = "data/replies.json"
BASES = "data/bases.json"
OTHER = "прочее"   # ник не найден ни в одной базе (ручные отправки и т.п.)


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


if __name__ == "__main__":
    print(summary_text())
