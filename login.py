#!/usr/bin/env python3
"""
login.py — залогинить аккаунт из терминала (запасной способ, обычно логинят на сайте).
Запуск:  python3 login.py имя_аккаунта
Сессия сохраняется в data/имя_аккаунта.session
"""

import os
import sys
import json
from telethon.sync import TelegramClient

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.makedirs("data", exist_ok=True)

try:
    _c = json.load(open("data/config.json", encoding="utf-8"))
    API_ID, API_HASH = int(_c.get("api_id") or 0), _c.get("api_hash") or ""
except Exception:
    sys.exit("Сначала введи api-ключи в онбординге на сайте (data/config.json пуст).")

session = sys.argv[1] if len(sys.argv) > 1 else "akk3"
path = os.path.join("data", session)

with TelegramClient(path, API_ID, API_HASH) as client:
    me = client.get_me()
    print("\nЗАЛОГИНЕН УСПЕШНО ✓")
    print(f"  аккаунт: {me.first_name or ''} @{me.username or '—'} (id {me.id})")
    print(f"  сессия сохранена: data/{session}.session")
