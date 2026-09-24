#!/usr/bin/env python3
"""
notify_replies.py — проверяет ответы лидов и шлёт новые в Telegram-бота.
Запускается по таймеру. Не мешает рассылке (ждёт, если send_campaign работает).
"""

import os
import sys
import json
import glob
import subprocess
import urllib.request
import urllib.parse

os.chdir(os.path.dirname(os.path.abspath(__file__)))

BOT = os.environ.get("TG_BOT_TOKEN", "")
CHAT = os.environ.get("TG_CHAT_ID", "")
REPLIES = "data/replies.json"
NOTIFIED = "data/notified.json"
ACCOUNTS = "data/accounts.json"


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _send(text):
    data = urllib.parse.urlencode({
        "chat_id": CHAT, "text": text, "disable_web_page_preview": "true"
    }).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{BOT}/sendMessage",
                               data=data, timeout=15)
        return True
    except Exception as e:
        print("tg send error:", e)
        return False


def _sessions():
    confirmed = set(_load(ACCOUNTS, []))
    files = set(os.path.basename(s)[:-8] for s in glob.glob("data/*.session"))
    return sorted(confirmed & files) if confirmed else sorted(files)


def main():
    # не мешаем рассылке — если она идёт, сессии заняты, ждём следующего цикла
    if subprocess.run(["pgrep", "-f", "send_campaign.py"],
                      capture_output=True).returncode == 0:
        print("рассылка идёт — пропускаю проверку ответов")
        return

    accs = _sessions()
    if not accs:
        print("нет аккаунтов")
        return

    # обновляем replies.json их же скриптом
    try:
        subprocess.run([sys.executable, "check.py", "replies", ",".join(accs)],
                       timeout=900)
    except Exception as e:
        print("check.py error:", e)

    replies = _load(REPLIES, {})
    notified = _load(NOTIFIED, {})
    new = 0
    for nick, info in replies.items():
        key = info.get("когда", "") + "|" + (info.get("текст", "")[:50])
        if notified.get(nick) == key:
            continue                       # про этот ответ уже слали
        try:
            import bot_kb
            bot_kb.push_draft(nick, info.get("аккаунт", ""),
                              info.get("текст", ""), info.get("когда", ""))
            notified[nick] = key
            new += 1
        except Exception as e:
            print("push_draft error:", e)
    json.dump(notified, open(NOTIFIED, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"новых уведомлений отправлено: {new}")


if __name__ == "__main__":
    main()
