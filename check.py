#!/usr/bin/env python3
"""
check.py — две проверки, обе только читают Telegram и ничего не отправляют.

    python3 check.py leads    — прогнать ники базы: какие вообще существуют
    python3 check.py replies  — кто из тех, кому писали, ответил

Запускается из дашборда кнопками, результат кладётся в data/ и подхватывается
на главном экране.
"""

import os
import csv
import sys
import json
import time
import random
from datetime import datetime

import openpyxl

import tg
from errors_map import cell_text, err_code, is_permanent_exc

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LEADS = "data/leads.xlsx"
LOG = "data/sent_log.csv"
INVALID = "data/invalid.json"    # ники, которых не существует
REPLIES = "data/replies.json"    # кто ответил
RUNNING = "data/checking.json"   # чтобы дашборд знал, что проверка идёт
NICK_COL = "ник"

CHECK_PAUSE = (2, 6)             # между запросами: чтение дешевле отправки, но не даром
MAX_CHECKS = 200
REPLY_LIMIT = 600               # ответы: проверяем всех (свежих первыми)                 # предохранитель на один запуск


def _mark_running(what):
    json.dump({"что": what, "начали": datetime.now().strftime("%Y-%m-%d %H:%M")},
              open(RUNNING, "w", encoding="utf-8"), ensure_ascii=False)


def _clear_running():
    try:
        json.dump({}, open(RUNNING, "w", encoding="utf-8"))
    except Exception:
        pass


def _load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return default


def _nicks_from_base():
    if not os.path.exists(LEADS):
        return []
    ws = openpyxl.load_workbook(LEADS).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h) if h is not None else "" for h in rows[0]]
    try:
        i = header.index(NICK_COL)
    except ValueError:
        return []
    return [cell_text(r[i]) for r in rows[1:] if i < len(r) and cell_text(r[i])]


def _sent_nicks():
    """Кому реально ушло — только им есть смысл искать ответ."""
    out = {}
    if not os.path.exists(LOG):
        return out
    for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
        if r.get("статус") == "ok":
            out[r.get("ник", "")] = r.get("аккаунт", "")
    out.pop("", None)
    return out


# ─── проверка базы: существуют ли ники ─────────────────────────────────
def check_leads(sessions):
    invalid = _load_json(INVALID, {})
    known_bad = set(invalid)
    sent = set(_sent_nicks())
    todo = [n for n in _nicks_from_base() if n not in known_bad and n not in sent][:MAX_CHECKS]
    if not todo:
        print("Проверять нечего: все ники уже проверены или им уже писали.")
        return

    clients = tg.open_clients(sessions)
    if not clients:
        print("Нет ни одного рабочего аккаунта — проверять нечем.")
        return
    names = list(clients)
    print(f"\nПроверяю {len(todo)} ников через {len(names)} акк(ов). Ничего не отправляю.\n")

    ok = 0
    try:
        for i, nick in enumerate(todo):
            acc = names[i % len(names)]
            try:
                clients[acc].get_entity(nick)
                ok += 1
                print(f"[{i+1}/{len(todo)}] ✓ {nick}")
                invalid.pop(nick, None)
            except Exception as e:
                if is_permanent_exc(e):
                    invalid[nick] = err_code(e)
                    print(f"[{i+1}/{len(todo)}] ✗ {nick}: ника не существует")
                else:
                    print(f"[{i+1}/{len(todo)}] ? {nick}: {e} (повторим потом)")
            json.dump(invalid, open(INVALID, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            if i < len(todo) - 1:
                time.sleep(random.randint(*CHECK_PAUSE))
    finally:
        tg.close_clients(clients)
    print(f"\nГотово: {ok} живых, {len(invalid)} мёртвых. Мёртвым рассылка писать не будет.")


# ─── проверка ответов ──────────────────────────────────────────────────
def check_replies(sessions):
    sent = _sent_nicks()
    if not sent:
        print("Ещё некому было отвечать: рассылка пока ничего не отправила.")
        return

    clients = tg.open_clients(sessions)
    if not clients:
        print("Нет ни одного рабочего аккаунта.")
        return

    replies = _load_json(REPLIES, {})
    found = 0
    print(f"\nСмотрю диалоги по {len(sent)} лидам. Только читаю.\n")
    try:
        items = list(sent.items())
        items.reverse()   # свежие лиды первыми — их ответы свежее и важнее
        for i, (nick, acc) in enumerate(items[:REPLY_LIMIT]):
            client = clients.get(acc)
            if client is None:
                print(f"[{i+1}] пропуск {nick}: акк {acc} не открылся")
                continue
            try:
                ent = client.get_entity(nick)
                incoming = [m for m in client.iter_messages(ent, limit=15) if not m.out]
                if incoming:
                    last = incoming[0]
                    replies[nick] = {
                        "когда": last.date.strftime("%Y-%m-%d %H:%M") if last.date else "",
                        "аккаунт": acc,
                        "текст": (last.message or "")[:300],
                    }
                    found += 1
                    print(f"[{i+1}] 💬 {nick}: {(last.message or '')[:60]}")
                else:
                    replies.pop(nick, None)
            except Exception as e:
                print(f"[{i+1}] ? {nick}: {e}")
            json.dump(replies, open(REPLIES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            time.sleep(random.randint(*CHECK_PAUSE))
    finally:
        tg.close_clients(clients)
    rate = round(100.0 * len(replies) / max(1, len(sent)))
    print(f"\nГотово: ответили {len(replies)} из {len(sent)} — это {rate}% reply rate.")


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    sessions = [s for s in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if s.strip()]
    if not sessions:
        sessions = sorted(_load_json("data/accounts.json", []))
    if mode not in ("leads", "replies"):
        sys.exit("Как запускать: python3 check.py leads|replies [акк1,акк2]")
    _mark_running(mode)
    try:
        (check_leads if mode == "leads" else check_replies)(sessions)
    finally:
        _clear_running()


if __name__ == "__main__":
    main()
