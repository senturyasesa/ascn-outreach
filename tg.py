#!/usr/bin/env python3
"""
tg.py — подключение к Telegram. Один код на все скрипты: движок рассылки,
проверку базы и проверку ответов.

Держит в себе только «как открыть клиента»: ключи, прокси, профиль устройства.
Ничего про лидов и рассылку не знает.
"""

import os
import csv
import time
import json
import shutil
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


import concurrent.futures as _cf


def _run_timeout(fn, timeout=25):
    """Выполнить fn с жёстким таймаутом (для веб-отправки, чтоб не висло вечно).
    Возвращает результат, либо None если завис."""
    ex = _cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except _cf.TimeoutError:
        return None
    finally:
        ex.shutdown(wait=False)


def _open_copy(acc):
    """Открыть аккаунт с КОПИИ .session, чтобы не конфликтовать с демоном
    рассылки за один файл (SQLite-замок). Копию делаем свежую каждый раз —
    auth_key тот же, Telegram спокойно держит второй коннект на том же ключе."""
    api_id, api_hash = credentials()
    src = os.path.join(SESS_DIR, acc + ".session")
    if not os.path.exists(src):
        return None
    d = os.path.join(SESS_DIR, "_inbox")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, acc + ".session")
    try:
        for suf in (".session-journal", ".session-wal", ".session-shm"):
            j = os.path.join(d, acc + suf)
            if os.path.exists(j):
                os.remove(j)
        shutil.copy2(src, dst)
    except Exception:
        pass
    try:
        c = TelegramClient(os.path.join(d, acc), api_id, api_hash,
                           proxy=proxy_for(acc), flood_sleep_threshold=60,
                           **C.device_for(acc))
        c.connect()
        if c.is_user_authorized():
            return c
        c.disconnect()
    except Exception:
        pass
    return None


def _norm_nick(n):
    return "@" + str(n or "").lstrip("@").strip().lower()


def _local_history(nick):
    """Собрать диалог из локальных логов (без Telegram): что мы отправили
    (sent_text.csv) + их ответ (replies.json). Чтобы окно не было пустым."""
    key = _norm_nick(nick)
    msgs = []
    # наши исходящие
    try:
        for r in csv.DictReader(open("data/sent_text.csv", encoding="utf-8-sig")):
            if _norm_nick(r.get("ник")) == key and (r.get("текст") or "").strip():
                msgs.append({"out": True, "text": r["текст"].strip(),
                             "date": (r.get("время") or "")[5:16]})
    except Exception:
        pass
    msgs = msgs[-3:]   # последние наши сообщения этому лиду
    # их ответ
    try:
        rep = json.load(open("data/replies.json", encoding="utf-8"))
        info = rep.get(key) or rep.get("@" + str(nick).lstrip("@"))
        if isinstance(info, dict) and (info.get("текст") or "").strip():
            msgs.append({"out": False, "text": info["текст"].strip(),
                         "date": (info.get("когда") or "")[5:16]})
    except Exception:
        pass
    return msgs


def get_history(acc, nick, limit=25):
    """Последние сообщения диалога acc↔nick. -> (list|None, err|None).
    Живую историю тянем с копии сессии; если недоступна — показываем
    локальный лог (наши отправки + их ответ), чтобы диалог не был пустым."""
    res = _run_timeout(lambda: _get_history_raw(acc, nick, limit), 25)
    if res and res[0]:
        return res
    local = _local_history(nick)
    if local:
        note = None if (res and res[0]) else "живая история недоступна — показан локальный лог"
        return local, note
    if res:
        return res
    return None, "аккаунт не отвечает (завис сессия/прокси) — обнови позже"


def _get_history_raw(acc, nick, limit=25):
    c = _open_copy(acc)
    if c is None:
        return None, "не удалось открыть аккаунт"
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
        try:
            c.disconnect()
        except Exception:
            pass


def send_reply(acc, nick, text):
    """Отправить text лиду nick аккаунтом acc. -> (ok, err).
    Шлём с копии сессии (не деремся с демоном) и с жёстким таймаутом."""
    res = _run_timeout(lambda: _send_reply_raw(acc, nick, text), 30)
    if res is None:
        return False, "аккаунт не отвечает (завис сессия/прокси) — попробуй позже или проверь акк"
    return res


def _send_reply_raw(acc, nick, text):
    c = _open_copy(acc)
    if c is None:
        return False, "аккаунт сейчас недоступен (занят рассылкой/прокси) — попробуй через минуту"
    try:
        ent = c.get_entity(nick)
        c.send_message(ent, text)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            c.disconnect()
        except Exception:
            pass
