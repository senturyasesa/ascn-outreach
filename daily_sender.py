#!/usr/bin/env python3
"""
daily_sender.py — дневной планировщик рассылки.

Вводишь цель (сообщений в день) в data/daily_plan.json — демон растягивает её
по рабочему окну 09:00–21:00 МСК, шлёт равномерно round-robin по аккам,
уважает дневные лимиты. Недосланное само переносится на завтра (берёт из базы).

Запуск:
    python3 daily_sender.py           боевой демон (шлёт)
    python3 daily_sender.py --dry     сухой прогон: печатает расчёт, НЕ шлёт

Не запускается одновременно с ручной рассылкой (send_campaign) — ждёт её.
"""

import os
import csv
import sys
import json
import time
import random
import signal
import subprocess
from datetime import datetime, timedelta, timezone

SEND_TIMEOUT = 45   # сек: предохранитель на подключение+отправку одного письма


class _SendTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _SendTimeout()

import openpyxl

import tg
import campaign as C
import alerts
import spambot
from errors_map import cell_text, err_code, is_account_dead, is_permanent

os.chdir(os.path.dirname(os.path.abspath(__file__)))

DRY = "--dry" in sys.argv

LEADS = "data/leads.xlsx"
LOG = "data/sent_log.csv"
SENDING = "data/sending.json"
INVALID = "data/invalid.json"
SENT_TEXT = "data/sent_text.csv"
PLAN = "data/daily_plan.json"
NICK_COL = "ник"
MSG_COL = "сообщение для захода"
LOG_FIELDS = ["ник", "статус", "аккаунт", "время", "ошибка"]

MSK = timezone(timedelta(hours=3))
WIN_START = 9    # 09:00 МСК
WIN_END = 22     # сегодня добиваем
MIN_GAP = 45     # не чаще раза в 45 сек
MAX_GAP = 1800   # не реже раза в 30 мин (иначе на паузе висим полдня)
RUSH = 0.45       # догон


def now_msk():
    return datetime.now(timezone.utc).astimezone(MSK)


def in_window(dt=None):
    dt = dt or now_msk()
    return WIN_START <= dt.hour < WIN_END


def seconds_to_window_end(dt=None):
    dt = dt or now_msk()
    end = dt.replace(hour=WIN_END, minute=0, second=0, microsecond=0)
    return max(0, (end - dt).total_seconds())


def seconds_to_next_window(dt=None):
    """Сколько спать до следующего 09:00 МСК."""
    dt = dt or now_msk()
    start = dt.replace(hour=WIN_START, minute=0, second=0, microsecond=0)
    if dt.hour >= WIN_START:
        start = start + timedelta(days=1)
    return max(60, (start - dt).total_seconds())


def load_plan():
    try:
        p = json.load(open(PLAN, encoding="utf-8"))
        return int(p.get("target", 0)), bool(p.get("active", False))
    except Exception:
        return 0, False


def sent_count_today():
    """Сколько сообщений (ok + fail) ушло СЕГОДНЯ — по всем аккам.
    Дневная цель считается по всем отправкам за день (и ручным, и дневным)."""
    day = now_msk().strftime("%Y-%m-%d")
    # лог пишет время в локальном времени сервера (UTC). Сопоставляем по дате UTC-стороны:
    n = 0
    utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            t = str(r.get("время", ""))
            # считаем ТОЛЬКО доставленные (ok) — цель = реально дошедшие сообщения
            if (t[:10] == day or t[:10] == utc_day) and r.get("статус") == "ok":
                n += 1
    return n


def _broadcast():
    try:
        return open("data/broadcast.txt", encoding="utf-8").read().strip()
    except Exception:
        return ""


def load_sent():
    done = set()
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            st = r.get("статус")
            if st == "ok":
                done.add(r["ник"])
            elif st == "fail" and is_permanent(r.get("ошибка", "")):
                done.add(r["ник"])
    return done


def build_queue():
    bc = _broadcast()
    wb = openpyxl.load_workbook(LEADS)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in rows[0]]
    leads = [dict(zip(header, ["" if v is None else v for v in r])) for r in rows[1:]]
    for r in leads:
        r[NICK_COL] = cell_text(r.get(NICK_COL))
        r[MSG_COL] = cell_text(r.get(MSG_COL))
    sent = load_sent()
    invalid = set()
    if os.path.exists(INVALID):
        try:
            invalid = set(json.load(open(INVALID, encoding="utf-8")))
        except Exception:
            pass
    return [r for r in leads
            if r[NICK_COL] and r[NICK_COL] not in sent and r[NICK_COL] not in invalid
            and (bc or r[MSG_COL])], bc


def all_accounts():
    import glob
    confirmed = []
    try:
        confirmed = json.load(open("data/accounts.json", encoding="utf-8"))
    except Exception:
        pass
    files = set(os.path.basename(s)[:-8] for s in glob.glob("data/*.session"))
    accs = [a for a in confirmed if a in files] if confirmed else sorted(files)
    # не трогаем чёрный список — на всякий случай ещё и по имени
    try:
        bl = set(json.load(open("data/blacklist.json", encoding="utf-8")).keys())
    except Exception:
        bl = set()
    return [a for a in accs if a not in bl and not spambot.is_frozen(a)]


def manual_running():
    return subprocess.run(["pgrep", "-f", "send_campaign.py"],
                          capture_output=True).returncode == 0


def compute_gap(target, sent_today):
    """Пауза до следующей отправки: равномерно до конца окна."""
    remaining = max(1, target - sent_today)
    gap = seconds_to_window_end() / remaining
    gap = max(MIN_GAP, min(MAX_GAP, gap))
    return gap


# ─────────────── СУХОЙ ПРОГОН ───────────────
def dry_run():
    target, active = load_plan()
    if target <= 0:
        target = 50   # для показа
    dt = now_msk()
    queue, bc = build_queue()
    accs = all_accounts()
    limits = C.load_limits()
    today = C.sent_today()
    cap_total = sum(C.daily_cap(a, limits) for a in accs)
    left = {a: C.remaining(a, limits, today) for a in accs}
    room = sum(left.values())
    sent_today = sent_count_today()

    print("=" * 56)
    print("СУХОЙ ПРОГОН дневного планировщика (ничего не отправляю)")
    print("=" * 56)
    print(f"Сейчас (МСК):        {dt.strftime('%Y-%m-%d %H:%M')}  "
          f"({'в окне' if in_window() else 'ВНЕ окна 09-21'})")
    print(f"Цель на день:        {target} сообщений")
    print(f"Режим:               {'ЕДИНЫЙ (broadcast)' if bc else 'персональный из базы'}")
    print(f"Аккаунтов в работе:  {len(accs)}  ({', '.join(accs)})")
    print(f"Лидов в очереди:     {len(queue)}")
    print(f"Уже ушло сегодня:    {sent_today}")
    print(f"Дневная ёмкость (сумма лимитов аккаунтов): {cap_total}, свободно сейчас {room}")
    print("-" * 56)

    plan_n = min(target, len(queue), room)
    if not in_window():
        wait_h = seconds_to_next_window() / 3600
        print(f"Сейчас вне окна — старт в 09:00 МСК (через {wait_h:.1f} ч).")
    remaining = max(1, target - sent_today)
    gap = compute_gap(target, sent_today)
    win_left_h = seconds_to_window_end() / 3600
    print(f"Осталось окна сегодня:  {win_left_h:.1f} ч")
    print(f"Отправлю сегодня:       {plan_n} (из цели {target})")
    print(f"Интервал между письмами: ~{gap/60:.1f} мин "
          f"(равномерно до 21:00, ±30% рандом)")
    print("-" * 56)
    # как распределится по аккам (round-robin)
    dist = {a: 0 for a in accs}
    ai = 0
    for _ in range(plan_n):
        for _try in range(len(accs)):
            a = accs[ai % len(accs)]
            ai += 1
            if left.get(a, 0) - dist[a] > 0:
                dist[a] += 1
                break
    print("Распределение по аккам сегодня:")
    for a in accs:
        print(f"  {a:24s} {dist[a]}  (лимит {C.daily_cap(a, limits)}, "
              f"свободно {left[a]})")
    print("-" * 56)
    if len(queue) < target:
        print(f"⚠️  В очереди {len(queue)} лидов < цели {target} — "
              f"уйдёт {len(queue)}, потом база кончится.")
    if room < target:
        print(f"⚠️  Дневная ёмкость {room} < цели {target} — "
              f"упрёмся в лимиты, остаток на завтра.")
    print("Боевой режим: python3 daily_sender.py  (без --dry)")


# ─────────────── БОЕВОЙ ДЕМОН ───────────────
_turn = [0]
_skips = [0]


def pick_account(accs, left):
    """Round-robin по аккам с остатком дневного лимита."""
    for _ in range(len(accs)):
        a = accs[_turn[0] % len(accs)]
        _turn[0] += 1
        if left.get(a, 0) > 0:
            return a
    return None


def send_one(acc, lead, bc):
    """Открыть один аккаунт, отправить одному лиду, записать в лог.
    Возвращает 'ok' | 'fail' | 'dead'."""
    nick = lead[NICK_COL]
    text, choices = C.render_message(bc or lead[MSG_COL], lead, return_choices=True)
    text = C.rewrite(text, broadcast=bool(bc))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    json.dump([nick], open(SENDING, "w", encoding="utf-8"), ensure_ascii=False)
    clients = {}
    status, err = "ok", ""
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(SEND_TIMEOUT)   # предохранитель: если подключение зависло — прервём
    try:
        clients = tg.open_clients([acc])
        if acc not in clients:
            status, err = "skip", "open_failed"
            print(f"  {acc}: не открылся, пропускаю (лид вернётся в очередь)")
        else:
            client = clients[acc]
            ent = client.get_entity(nick)
            with client.action(ent, "typing"):
                time.sleep(C.typing_seconds(text))
                client.send_message(ent, text)
            print(f"  ✓ {nick}  ←  {acc}")
    except _SendTimeout:
        status, err = "skip", "timeout"
        print(f"  ⏰ {acc}: завис >{SEND_TIMEOUT}с — пропускаю акк, беру следующий")
    except Exception as e:
        status = "dead" if is_account_dead(e) else "fail"
        err = err_code(e)
        print(f"  ✗ {nick}  ←  {acc}: {e}")
        if alerts.is_flood(e):
            alerts.alert_flood(acc, e)
            spambot.enqueue(acc)
    finally:
        signal.alarm(0)

    # timeout/open_failed НЕ пишем в лог: это проблема аккаунта, а не лида —
    # лид останется в очереди и уйдёт следующим аккаунтом
    if status not in ("skip",):
        new_log = not os.path.exists(LOG)
        with open(LOG, "a", newline="", encoding="utf-8-sig") as logf:
            w = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
            if new_log:
                w.writeheader()
            w.writerow({"ник": nick, "статус": "ok" if status == "ok" else "fail",
                        "аккаунт": acc, "время": ts, "ошибка": err})
        if status == "ok":
            _log_text(nick, acc, ts, text, choices)
    try:
        tg.close_clients(clients)
    except Exception:
        pass
    json.dump([], open(SENDING, "w", encoding="utf-8"))
    return status


def _log_text(nick, acc, ts, text, choices):
    new = not os.path.exists(SENT_TEXT)
    with open(SENT_TEXT, "a", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=["ник", "аккаунт", "время", "вариант", "текст"])
        if new:
            wr.writeheader()
        wr.writerow({"ник": nick, "аккаунт": acc, "время": ts,
                     "вариант": " | ".join(choices), "текст": text})


def daemon():
    print("daily_sender: демон запущен, окно %02d-%02d МСК" % (WIN_START, WIN_END))
    while True:
        target, active = load_plan()
        if not active or target <= 0:
            time.sleep(60)
            continue
        spambot.thaw_expired()      # вернуть акки, у кого срок заморозки вышел
        spambot.process_queue()     # проверить через @SpamBot тех, кто словил флуд
        if not in_window():
            s = seconds_to_next_window()
            print("вне окна, сплю до 09:00 МСК (~%.1fч)" % (s / 3600))
            time.sleep(min(s, 3600))
            continue
        if manual_running():
            print("ручная рассылка идёт — жду, чтоб не задвоить")
            time.sleep(120)
            continue
        sent_today = sent_count_today()
        if sent_today >= target:
            s = seconds_to_next_window()
            print("цель %d на сегодня выполнена, сплю до завтра" % target)
            time.sleep(min(s, 3600))
            continue
        queue, bc = build_queue()
        if not queue:
            print("очередь пуста (нет текста или база кончилась) — жду")
            time.sleep(300)
            continue
        accs = all_accounts()
        limits = C.load_limits()
        today = C.sent_today()
        left = {a: C.remaining(a, limits, today) for a in accs}
        acc = pick_account(accs, left)
        if acc is None:
            s = seconds_to_next_window()
            print("лимиты всех аккаунтов на сегодня выбраны — сплю до завтра")
            time.sleep(min(s, 3600))
            continue
        res = send_one(acc, queue[0], bc)
        if res == "skip":
            # акк завис/не открылся — НЕ ждём полный интервал, сразу следующий акк
            _skips[0] += 1
            if _skips[0] >= len(accs):
                print("    все аккаунты подряд не открываются — пауза 5 мин")
                _skips[0] = 0
                time.sleep(300)
            else:
                time.sleep(5)
            continue
        _skips[0] = 0
        gap = compute_gap(target, sent_count_today()) * RUSH * random.uniform(0.8, 1.2)
        gap = max(MIN_GAP, min(MAX_GAP, gap))
        print("    пауза %.1f мин (доставлено %d/%d)" % (gap / 60, sent_count_today(), target))
        time.sleep(gap)


if __name__ == "__main__":
    if DRY:
        dry_run()
    else:
        daemon()
