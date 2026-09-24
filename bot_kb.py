#!/usr/bin/env python3
"""bot_kb.py — отправка черновика ответа в Telegram-бота с кнопками
[✅ Отправить] [✏️ Редактировать] [✍️ Напишу сам] и хранилище черновиков.

Черновики лежат в data/pending_drafts.json по короткому id; callback-кнопки несут
только id (текст ответа в 64 байта callback_data не влезает). Слушатель нажатий —
bot_listener.py.
"""

import os
import json
import time
import hashlib
import urllib.request
import urllib.parse

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import tg
import ai_sales
from alerts import BOT, CHAT

PENDING = "data/pending_drafts.json"
API = f"https://api.telegram.org/bot{BOT}/"


def api(method, payload, timeout=15):
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(API + method, data=data, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        print("tg api error:", method, e)
        return {}


def load_pending():
    try:
        return json.load(open(PENDING, encoding="utf-8"))
    except Exception:
        return {}


def save_pending(p):
    json.dump(p, open(PENDING, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _id(nick, when):
    return hashlib.md5((str(nick) + "|" + str(when)).encode()).hexdigest()[:10]


def _kb(pid):
    return json.dumps({"inline_keyboard": [
        [{"text": "✅ Отправить", "callback_data": "s|" + pid},
         {"text": "✏️ Редактировать", "callback_data": "e|" + pid}],
        [{"text": "✍️ Напишу сам", "callback_data": "k|" + pid}],
    ]})


def push_draft(nick, acc, reply_text, when=""):
    """Сгенерить черновик и отправить в бота с кнопками. -> True если отправлено.
    Если последнее сообщение в диалоге НАШЕ (мы уже ответили) — черновик не шлём."""
    try:
        msgs, _ = tg.get_history(acc, nick, limit=6)
        if msgs and msgs[-1].get("out"):
            print(f"{nick}: последнее сообщение наше — уже ответлено, черновик не шлю")
            return False
    except Exception:
        pass
    text, needs, err = ai_sales.draft(acc, nick)
    head = (f"💬 {nick} ответил (акк {acc}):\n"
            f"{(reply_text or '')[:350]}\n\n")

    if err or not text:
        # черновик не собрался — шлём без кнопок, зовём ответить вручную
        api("sendMessage", {
            "chat_id": CHAT,
            "text": head + f"🤖 черновик не собрался ({err or 'пусто'}).\n"
                           f"Ответь вручную: https://t.me/{nick.lstrip('@')}",
            "disable_web_page_preview": "true"})
        return True

    pid = _id(nick, when or str(time.time()))
    p = load_pending()
    p[pid] = {"nick": nick, "acc": acc, "text": text,
              "reply": reply_text or "", "when": when, "ts": time.time()}
    save_pending(p)

    flag = "⚠️ ИИ: тут лучше ответить лично (сложный/горячий)\n\n" if needs else ""
    msg = head + flag + "🤖 Черновик ответа:\n" + text
    api("sendMessage", {
        "chat_id": CHAT, "text": msg,
        "reply_markup": _kb(pid),
        "disable_web_page_preview": "true"})
    return True
