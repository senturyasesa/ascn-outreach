#!/usr/bin/env python3
"""
tg.py — подключение к Telegram. Один код на все скрипты: движок рассылки,
проверку базы и проверку ответов.

Держит в себе только «как открыть клиента»: ключи, прокси, профиль устройства.
Ничего про лидов и рассылку не знает.
"""

import os
import time
import json
from urllib.parse import urlparse

from telethon.sync import TelegramClient

import campaign as C

SESS_DIR = "data"
CONFIG = "data/config.json"
PROXIES = "data/proxies.json"


def credentials():
    try:
        c = json.load(open(CONFIG, encoding="utf-8"))
        return int(c.get("api_id") or 0), c.get("api_hash") or ""
    except Exception:
        return 0, ""


def parse_proxy(url):
    """socks5://user:pass@host:port → dict для Telethon. Пусто/мусор → None."""
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


def proxy_for(name):
    if os.path.exists(PROXIES):
        try:
            return parse_proxy(json.load(open(PROXIES, encoding="utf-8")).get(name))
        except Exception:
            return None
    return None


def open_clients(names, quiet=False):
    """Открывает клиентов по именам сессий. Возвращает {имя: client}.
    Неавторизованные и недоступные молча пропускаются (с сообщением в консоль)."""
    api_id, api_hash = credentials()
    clients = {}
    for s in names:
        try:
            c = TelegramClient(os.path.join(SESS_DIR, s), api_id, api_hash,
                               proxy=proxy_for(s), flood_sleep_threshold=60,
                               **C.device_for(s))   # свой профиль клиента на аккаунт
            c.connect()
            if c.is_user_authorized():
                clients[s] = c
                if not quiet:
                    print(f"  аккаунт {s}: готов")
            else:
                if not quiet:
                    print(f"  аккаунт {s}: не авторизован, пропускаю")
                c.disconnect()
        except Exception as e:
            if not quiet:
                print(f"  аккаунт {s}: ошибка подключения ({e}), пропускаю")
    return clients


def close_clients(clients):
    for c in (clients or {}).values():
        try:
            c.disconnect()
        except Exception:
            pass


def get_history(acc, nick, limit=25):
    """Последние сообщения диалога acc↔nick. -> (list|None, err|None).
    Каждое: {out, text, date}."""
    cl = {}
    for _try in range(4):
        cl = open_clients([acc], quiet=True)
        if acc in cl:
            break
        close_clients(cl); cl = {}
        time.sleep(2.5)
    if acc not in cl:
        return None, "аккаунт сейчас занят рассылкой — обнови страницу через 10 секунд"
    c = cl[acc]
    try:
        ent = c.get_entity(nick)
        msgs = []
        for m in c.iter_messages(ent, limit=limit):
            msgs.append({"out": bool(m.out),
                         "text": m.message or "",
                         "date": m.date.strftime("%d.%m %H:%M") if m.date else ""})
        msgs.reverse()   # старые сверху, свежие снизу
        return msgs, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        close_clients(cl)


def send_reply(acc, nick, text):
    """Отправить text лиду nick аккаунтом acc. -> (ok, err)."""
    cl = {}
    for _try in range(4):
        cl = open_clients([acc], quiet=True)
        if acc in cl:
            break
        close_clients(cl); cl = {}
        time.sleep(2.5)
    if acc not in cl:
        return False, "аккаунт сейчас занят рассылкой — попробуй через 10 секунд"
    c = cl[acc]
    try:
        ent = c.get_entity(nick)
        c.send_message(ent, text)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        close_clients(cl)
