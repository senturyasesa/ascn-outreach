#!/usr/bin/env python3
"""alerts.py — мгновенные уведомления в Telegram-бот о проблемах аккаунтов.

Главное: поймали «Too many requests» / флуд-лимит на аккаунте → сразу пишем
Денису в бот с ИМЕНЕМ аккаунта, чтобы было видно кто и когда упёрся в лимит.
Тот же бот и чат, что вечерний отчёт (report.py) и notify_replies.py.
"""

import os
import time
import urllib.parse
import urllib.request

from telethon import errors

BOT = os.environ.get("TG_BOT_TOKEN", "")
CHAT = os.environ.get("TG_CHAT_ID", "")

# что считаем «слишком много запросов / флуд-лимит аккаунта»
FLOOD_EXC = (
    errors.PeerFloodError,     # спам-блок: «Too many requests»
    errors.FloodWaitError,     # лимит запросов исчерпан (нужно ждать N сек)
    errors.SlowModeWaitError,  # медленный режим
)

# антиспам самих алертов: один и тот же акк не долбим чаще раза в 10 мин
_ALERT_GAP = 600
_last = {}


def is_flood(e):
    return isinstance(e, FLOOD_EXC)


def _send(text):
    try:
        data = urllib.parse.urlencode({
            "chat_id": CHAT, "text": text, "disable_web_page_preview": "true"
        }).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{BOT}/sendMessage", data=data, timeout=15)
        return True
    except Exception as ex:
        print(f"  (алерт не ушёл: {ex})")
        return False


def alert_flood(acc, e):
    """Прислать в бота, что аккаунт acc словил флуд-лимит."""
    now = time.time()
    if now - _last.get(acc, 0) < _ALERT_GAP:
        return  # недавно уже писали про этот акк — не спамим
    _last[acc] = now

    wait = getattr(e, "seconds", None)  # у FloodWaitError есть .seconds
    if isinstance(e, errors.FloodWaitError) and wait:
        mins = wait / 60
        detail = f"лимит запросов исчерпан, Telegram просит подождать {wait}с (~{mins:.0f} мин)"
    elif isinstance(e, errors.PeerFloodError):
        detail = "«Too many requests» — Telegram пометил аккаунт за частые сообщения незнакомцам (спам-блок)"
    elif isinstance(e, errors.SlowModeWaitError):
        detail = f"медленный режим, ждать {wait}с" if wait else "медленный режим"
    else:
        detail = str(e)

    hhmm = time.strftime("%H:%M")
    m = (f"🚫 ФЛУД-ЛИМИТ · {hhmm}\n\n"
         f"Аккаунт: {acc}\n"
         f"Что: {detail}\n\n"
         f"Убираю его из ротации на сегодня. Остальные акки продолжают слать.")
    _send(m)
    print(f"  🚫 алерт про флуд отправлен: {acc}")


def alert(text):
    """Произвольный алерт в тот же бот (на будущее)."""
    return _send(text)
