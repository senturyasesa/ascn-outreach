#!/usr/bin/env python3
"""bot_listener.py — слушает нажатия кнопок под черновиками в Telegram-боте.

[✅ Отправить]     -> шлём черновик клиенту с того же аккаунта
[✏️ Редактировать] -> бот просит новый текст, следующим сообщением ты его шлёшь
[✍️ Напишу сам]    -> убираем кнопки, ведёшь диалог сам

Долгий getUpdates-поллинг (webhook не нужен). Запускается сервисом ascn-bot.
"""

import os
import json
import time
import urllib.request
import urllib.parse

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import tg
import bot_kb
from alerts import BOT, CHAT

API = f"https://api.telegram.org/bot{BOT}/"
_edit = {}   # chat_id -> pid: ждём отредактированный текст


def api(method, payload, timeout=15):
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(API + method, data=data, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        print("api err", method, e)
        return {}


def answer(cb_id, text=""):
    api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})


def edit_text(chat, mid, text):
    api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text,
                            "disable_web_page_preview": "true"})


def _send_to_client(p, text):
    ok, err = tg.send_reply(p["acc"], p["nick"], text)
    return ok, err


def on_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")
    act, _, pid = data.partition("|")
    pend = bot_kb.load_pending()
    p = pend.get(pid)
    if not p:
        answer(cb["id"], "черновик устарел")
        if chat and mid:
            edit_text(chat, mid, "⌛ Черновик устарел, ответь на сайте или вручную.")
        return

    if act == "s":            # Отправить
        answer(cb["id"], "отправляю…")
        ok, err = _send_to_client(p, p["text"])
        edit_text(chat, mid,
                  (f"✅ Отправлено {p['nick']}:\n\n{p['text']}") if ok
                  else (f"❌ Не ушло ({err}). Попробуй на сайте.\n\n{p['text']}"))
        if ok:
            pend.pop(pid, None); bot_kb.save_pending(pend)

    elif act == "e":          # Редактировать
        answer(cb["id"], "жду твой текст")
        _edit[chat] = pid
        api("sendMessage", {"chat_id": chat,
                            "text": f"✏️ Пришли новый текст ответа для {p['nick']} "
                                    f"следующим сообщением. Отмена: /cancel"})

    elif act == "k":          # Напишу сам
        answer(cb["id"], "ок, сам")
        edit_text(chat, mid, f"✍️ Пишешь сам: {p['nick']}\n(черновик был:)\n\n{p['text']}")
        pend.pop(pid, None); bot_kb.save_pending(pend)


def on_message(m):
    chat = m.get("chat", {}).get("id")
    text = m.get("text", "")
    if chat not in _edit:
        return
    if text.strip() == "/cancel":
        _edit.pop(chat, None)
        api("sendMessage", {"chat_id": chat, "text": "отменил, кнопки на сообщении ещё активны"})
        return
    pid = _edit.pop(chat)
    pend = bot_kb.load_pending()
    p = pend.get(pid)
    if not p:
        api("sendMessage", {"chat_id": chat, "text": "черновик устарел"})
        return
    ok, err = _send_to_client(p, text)
    api("sendMessage", {"chat_id": chat,
                        "text": (f"✅ Отправлено {p['nick']}") if ok
                        else (f"❌ Не ушло: {err}")})
    if ok:
        pend.pop(pid, None); bot_kb.save_pending(pend)


def main():
    api("deleteWebhook", {})
    print("bot_listener: слушаю нажатия…")
    offset = None
    while True:
        try:
            payload = {"timeout": 25}
            if offset is not None:
                payload["offset"] = offset
            r = api("getUpdates", payload, timeout=40)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    on_callback(u["callback_query"])
                elif "message" in u:
                    on_message(u["message"])
        except Exception as e:
            print("loop err", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
