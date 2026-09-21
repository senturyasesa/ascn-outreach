#!/usr/bin/env python3
"""spambot.py — самодиагностика аккаунта через @SpamBot + заморозка.

При флуде акк сам идёт к @SpamBot (/start), читает приговор. Если аккаунт
ограничен — жмёт «This is a mistake» (обжалование) и морозится до даты
окончания. Замороженные акки исключаются из ротации (all_accounts) и
авто-возвращаются, когда срок вышел (thaw_expired).

Поток управления:
  send_one поймал флуд -> alerts.alert_flood + spambot.enqueue(acc)
  daemon в начале цикла -> spambot.thaw_expired() + spambot.process_queue()
"""

import os
import re
import json
import time
import signal
from datetime import datetime, timezone, timedelta

import tg
import alerts

os.chdir(os.path.dirname(os.path.abspath(__file__)))

FREEZE = "data/freeze.json"
QUEUE = "data/spambot_queue.json"
SPAMBOT = "SpamBot"          # @SpamBot — официальный бот Telegram
CHECK_TIMEOUT = 45           # сек на всю проверку одного акка
DEFAULT_FREEZE_DAYS = 3      # если дату окончания не распарсили

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})


class _TO(Exception):
    pass


def _alarm(s, f):
    raise _TO()


# ─────────────── хранилище заморозок ───────────────
def load_freeze():
    try:
        return json.load(open(FREEZE, encoding="utf-8"))
    except Exception:
        return {}


def save_freeze(d):
    json.dump(d, open(FREEZE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def is_frozen(acc):
    e = load_freeze().get(acc)
    if not e:
        return False
    try:
        return datetime.now(timezone.utc) < datetime.fromisoformat(e["until"])
    except Exception:
        return True   # кривой until — на всякий считаем замороженным


def freeze(acc, until_dt, raw=""):
    d = load_freeze()
    d[acc] = {"until": until_dt.isoformat(),
              "since": datetime.now(timezone.utc).isoformat(),
              "raw": (raw or "")[:400]}
    save_freeze(d)


def thaw_expired():
    """Разморозить акки, у которых срок вышел. Уведомить."""
    d = load_freeze()
    now = datetime.now(timezone.utc)
    changed = False
    for acc in list(d):
        try:
            expired = datetime.fromisoformat(d[acc]["until"]) <= now
        except Exception:
            expired = False
        if expired:
            del d[acc]
            changed = True
            alerts.alert(f"✅ Акк {acc} разморожен — срок вышел, вернул в рассылку.")
    if changed:
        save_freeze(d)


# ─────────────── очередь на проверку ───────────────
def enqueue(acc):
    try:
        q = json.load(open(QUEUE, encoding="utf-8"))
    except Exception:
        q = []
    if acc not in q:
        q.append(acc)
        json.dump(q, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False)


def _dequeue_all():
    try:
        q = json.load(open(QUEUE, encoding="utf-8"))
    except Exception:
        q = []
    json.dump([], open(QUEUE, "w", encoding="utf-8"))
    return q


# ─────────────── парсинг даты из ответа ───────────────
def _parse_until(text):
    """Ищем 'DD Month YYYY' с опциональным ', HH:MM'."""
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?', text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(2).lower())
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(1)),
                        int(m.group(4) or 0), int(m.group(5) or 0),
                        tzinfo=timezone.utc)
    except Exception:
        return None


# ─────────────── ядро проверки ───────────────
def _wait_reply(c, after_out=True, tries=6, gap=2.5):
    """Дождаться ответа @SpamBot (не нашего /start)."""
    for _ in range(tries):
        time.sleep(gap)
        msgs = c.get_messages(SPAMBOT, limit=1)
        if msgs and not (after_out and msgs[0].out):
            return msgs[0]
    return msgs[0] if msgs else None


def check(acc):
    """Сходить в @SpamBot аккаунтом acc. Вернуть {status, until, raw, appealed}.
    status: free | limited | unknown | error."""
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(CHECK_TIMEOUT)
    clients = {}
    try:
        clients = tg.open_clients([acc], quiet=True)
        if acc not in clients:
            return {"status": "error", "until": None,
                    "raw": "акк не открылся / не авторизован", "appealed": False}
        c = clients[acc]
        c.send_message(SPAMBOT, "/start")
        msg = _wait_reply(c)
        raw = (msg.text if msg else "") or ""
        appealed = False

        # обжалование: жмём кнопку со словом mistake
        try:
            if msg and msg.buttons:
                done = False
                for row in msg.buttons:
                    for b in row:
                        if "mistake" in (b.text or "").lower():
                            msg.click(text=b.text)
                            appealed = True
                            done = True
                            m2 = _wait_reply(c, after_out=False)
                            if m2 and m2.text:
                                raw = m2.text
                            break
                    if done:
                        break
        except Exception:
            pass

        low = raw.lower()
        if any(k in low for k in ("no limit", "good news", "free as a bird",
                                  "no restrictions", "not limited")):
            return {"status": "free", "until": None, "raw": raw, "appealed": appealed}
        until = _parse_until(raw)
        if until is None and any(k in low for k in ("limit", "block", "restrict", "ban")):
            until = datetime.now(timezone.utc) + timedelta(days=DEFAULT_FREEZE_DAYS)
            return {"status": "unknown", "until": until, "raw": raw, "appealed": appealed}
        return {"status": "limited" if until else "unknown",
                "until": until, "raw": raw, "appealed": appealed}
    except _TO:
        return {"status": "error", "until": None,
                "raw": f"таймаут >{CHECK_TIMEOUT}с", "appealed": False}
    except Exception as e:
        return {"status": "error", "until": None,
                "raw": f"{type(e).__name__}: {e}", "appealed": False}
    finally:
        signal.alarm(0)
        try:
            tg.close_clients(clients)
        except Exception:
            pass


def _msk(dt):
    return (dt + timedelta(hours=3)).strftime("%d.%m %H:%M")


def process_queue():
    """Проверить все акки из очереди: заморозить/уведомить по вердикту @SpamBot."""
    for acc in _dequeue_all():
        if is_frozen(acc):
            continue
        r = check(acc)
        st = r["status"]
        appeal = " (обжаловал)" if r.get("appealed") else ""
        if st == "free":
            alerts.alert(f"✅ @SpamBot по {acc}: лимитов нет{appeal}.")
        elif st == "limited" and r["until"]:
            freeze(acc, r["until"], r["raw"])
            alerts.alert(f"🧊 @SpamBot по {acc}: ОГРАНИЧЕН до {_msk(r['until'])} МСК{appeal}.\n"
                         f"Убрал из рассылки до разморозки.\n\n{r['raw'][:200]}")
        elif st == "unknown" and r["until"]:
            freeze(acc, r["until"], r["raw"])
            alerts.alert(f"⚠️ @SpamBot по {acc}: не разобрал ответ дословно, "
                         f"заморозил на {DEFAULT_FREEZE_DAYS}д на всякий{appeal}.\n\n{r['raw'][:200]}")
        else:
            alerts.alert(f"❓ @SpamBot по {acc}: не смог проверить ({r['raw'][:120]}).")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # ручная проверка: python3 spambot.py "ИмяАкка"
        import pprint
        pprint.pprint(check(sys.argv[1]))
    else:
        thaw_expired()
        process_queue()
