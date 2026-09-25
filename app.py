#!/usr/bin/env python3
"""
app.py — локальный веб-дашборд рассылки ASCN.
Запуск: двойной клик по «Запуск рассылки.command» (или python3 app.py).
Открывает http://127.0.0.1:8765
"""

import os
import re
import csv
import sys
import glob
import json
import random
import asyncio
import threading
import subprocess
import webbrowser
from urllib.parse import urlparse

import openpyxl
from flask import Flask, render_template_string, request, redirect, url_for, flash
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

import campaign as C
import tg
from errors_map import cell_text, is_permanent
import vault as V
import spambot
from ui import INBOX_TPL, DIALOG_TPL, MAIN_TPL, SETTINGS_TPL, ONBOARD_TPL, CODE_TPL, UNLOCK_TPL, STATS_TPL, FOLLOWUPS_TPL, ENGINE_TPL

os.chdir(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
try:
    import api
    app.register_blueprint(api.bp)
except Exception as _e:
    print("api blueprint error:", _e)
app.secret_key = "ascn-local-rassylka"

PORT = 8765
SESS_DIR = "data"             # тут лежат сессии аккаунтов и таблицы
CONFIG = "data/config.json"   # онбординг сохраняет сюда api-ключи пользователя
LEADS = "data/leads.xlsx"     # база лидов (Excel)
LOG = "data/sent_log.csv"     # журнал отправки
PROXIES = "data/proxies.json" # прокси по аккаунтам
SENDING = "data/sending.json" # кого сейчас отправляем (статус «отправляется»)
CHECKING = "data/checking.json" # идёт ли проверка базы/ответов
NICK_COL = "ник"


def load_config():
    """api_id/api_hash пользователя (вводятся в онбординге). Пусто → (0, '')."""
    if os.path.exists(CONFIG):
        try:
            c = json.load(open(CONFIG, encoding="utf-8"))
            return int(c.get("api_id") or 0), c.get("api_hash") or ""
        except Exception:
            return 0, ""
    return 0, ""


# ─── прокси ────────────────────────────────────────────────────────────
def parse_proxy(url):
    """socks5://user:pass@host:port → dict для Telethon. Пусто → None."""
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "socks5://" + url
    p = urlparse(url)
    if not p.hostname or not p.port:
        return None
    return {
        "proxy_type": p.scheme or "socks5",
        "addr": p.hostname,
        "port": p.port,
        "username": p.username or None,
        "password": p.password or None,
        "rdns": True,
    }


def load_proxies():
    if os.path.exists(PROXIES):
        try:
            return json.load(open(PROXIES, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_proxies(d):
    json.dump(d, open(PROXIES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
# ──────────────────────────────────────────────────────────────────────
MSG_COL = "сообщение для захода"
EDIT_COLS = ["ник", "главная боль", "сообщение для захода"]   # что можно править на сайте

# ─── постоянный asyncio-цикл в отдельном потоке (для логина через Telethon) ──
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


_pending = {}   # name -> (client, phone, phone_code_hash) — незавершённые логины


def start_login(name, phone, proxy_url=None):
    api_id, api_hash = load_config()
    proxy = parse_proxy(proxy_url)
    client = TelegramClient(os.path.join(SESS_DIR, name), api_id, api_hash, loop=_loop, proxy=proxy)

    async def go():
        await client.connect()
        sent = await client.send_code_request(phone)
        return sent.phone_code_hash

    phone_hash = _run(go())
    _pending[name] = (client, phone, phone_hash)
    if proxy_url:                       # запомним прокси за аккаунтом
        pr = load_proxies()
        pr[name] = proxy_url
        save_proxies(pr)


def finish_login(name, code=None, password=None):
    client, phone, phone_hash = _pending[name]

    async def go():
        if password is not None:
            await client.sign_in(password=password)
        else:
            await client.sign_in(phone, code, phone_code_hash=phone_hash)
        me = await client.get_me()
        await client.disconnect()
        return me

    try:
        me = _run(go())
        _pending.pop(name, None)
        accs = load_accounts()          # подтверждаем: вход реально прошёл
        accs.add(name)
        save_accounts(accs)
        return {"ok": me}
    except SessionPasswordNeededError:
        return {"need2fa": True}
    except Exception as e:
        return {"error": str(e)}


def logout(name):
    """Завершает сессию на стороне Telegram и удаляет .session файл."""
    api_id, api_hash = load_config()
    path = os.path.join(SESS_DIR, name)
    client = TelegramClient(path, api_id, api_hash, loop=_loop)

    async def go():
        await client.connect()
        await client.log_out()   # разлогинивает и удаляет файл сессии

    _run(go())
    # подчистим файл, если вдруг остался
    for ext in (".session", ".session-journal"):
        try:
            os.remove(path + ext)
        except OSError:
            pass


# ─── СЛОЙ ДАННЫХ (позже легко заменить CSV на Excel) ───────────────────
def _read_xlsx():
    wb = openpyxl.load_workbook(LEADS)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    header = [str(h) if h is not None else "" for h in rows[0]]
    data = [dict(zip(header, ["" if v is None else v for v in r])) for r in rows[1:]]
    return header, data


def load_leads():
    try:
        _, data = _read_xlsx()
        return data
    except FileNotFoundError:
        return []


def save_leads(header, data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "leads"
    ws.append(header)
    for r in data:
        ws.append([r.get(c, "") for c in header])
    wb.save(LEADS)


def load_sent():
    done = {}
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            done[r["ник"]] = r
    return done


def sending_active():
    # «отправляется» имеет смысл только если процесс рассылки реально жив
    try:
        return subprocess.run(["pgrep", "-f", "send_campaign.py"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def load_sending():
    if not sending_active():
        return set()   # рассылки нет — никто не «отправляется» (сбрасываем зависшие)
    if os.path.exists(SENDING):
        try:
            return set(json.load(open(SENDING, encoding="utf-8")))
        except Exception:
            return set()
    return set()


ACCOUNTS = "data/accounts.json"   # имена РЕАЛЬНО залогиненных аккаунтов


def load_checking():
    """Идёт ли сейчас проверка базы или ответов (для баннера на главной)."""
    try:
        if subprocess.run(["pgrep", "-f", "check.py"], capture_output=True).returncode != 0:
            return {}
    except Exception:
        return {}
    if os.path.exists(CHECKING):
        try:
            return json.load(open(CHECKING, encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def load_accounts():
    if os.path.exists(ACCOUNTS):
        try:
            return set(json.load(open(ACCOUNTS, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_accounts(names):
    json.dump(sorted(names), open(ACCOUNTS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def list_sessions():
    # показываем только подтверждённые (успешно вошли) И у кого есть файл сессии
    confirmed = load_accounts()
    files = set(os.path.basename(s)[:-8] for s in glob.glob(os.path.join(SESS_DIR, "*.session")))
    return sorted(confirmed & files)


def load_log():
    if not os.path.exists(LOG):
        return []
    return list(csv.DictReader(open(LOG, encoding="utf-8-sig")))
# ──────────────────────────────────────────────────────────────────────


@app.before_request
def require_unlock():
    if request.path.startswith('/api/'):
        return
    # данные зашифрованы — до ввода пароля не работает ничего:
    # config.json лежит внутри хранилища, читать его нечем
    if V.is_locked() and request.endpoint not in ("unlock", "unlock_post", "static"):
        return redirect(url_for("unlock"))


@app.before_request
def require_onboarding():
    if request.path.startswith('/api/'):
        return
    # пока не введены api-ключи — гоним на онбординг (кроме самих его страниц)
    if V.is_locked() or request.endpoint in ("onboarding", "onboarding_save", "static"):
        return
    api_id, api_hash = load_config()
    if not api_id or not api_hash:
        return redirect(url_for("onboarding"))


@app.route("/unlock")
def unlock():
    return render_template_string(UNLOCK_TPL)


@app.route("/unlock", methods=["POST"], endpoint="unlock_post")
def unlock_post():
    try:
        names = V.unlock(request.form.get("password", ""))
    except V.VaultError as e:
        flash(str(e))
        return redirect(url_for("unlock"))
    flash(f"Данные разблокированы: вернулось {len(names)} файлов.")
    return redirect(url_for("index"))


@app.route("/lock", methods=["POST"])
def lock():
    pwd = request.form.get("password", "")
    if pwd != request.form.get("password2", ""):
        flash("Пароли не совпали — ничего не менял.")
        return redirect(url_for("settings"))
    try:
        hidden = V.lock(pwd)
    except V.VaultError as e:
        flash(str(e))
        return redirect(url_for("settings"))
    flash(f"Спрятано {len(hidden)} файлов в data/vault.enc. Пароль нигде не сохранён.")
    return redirect(url_for("unlock"))


@app.route("/onboarding")
def onboarding():
    api_id, api_hash = load_config()
    return render_template_string(ONBOARD_TPL, api_id=api_id or "", api_hash=api_hash or "")


@app.route("/onboarding/save", methods=["POST"])
def onboarding_save():
    api_id = request.form.get("api_id", "").strip()
    api_hash = request.form.get("api_hash", "").strip()
    if not api_id.isdigit() or len(api_hash) < 30:
        flash("Проверь ключи: api_id это число, api_hash это строка ~32 символа.")
        return redirect(url_for("onboarding"))
    os.makedirs("data", exist_ok=True)
    json.dump({"api_id": int(api_id), "api_hash": api_hash},
              open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    flash("Ключи сохранены. Теперь добавь аккаунт — и можно слать.")
    return redirect(url_for("settings"))


@app.route("/")
def index():
    """Главный экран: статистика, отправка пачки, таблица лидов с правкой."""
    leads = load_leads()
    sent = load_sent()
    sending = load_sending()
    replies = C.load_replies()
    invalid = C.load_invalid()
    for i, l in enumerate(leads):
        l["_i"] = i          # исходный номер строки: правки сохраняются даже под фильтром
        nick = cell_text(l.get(NICK_COL))   # число в ячейке → строка, иначе статус не найдётся
        l[NICK_COL] = nick
        s = sent.get(nick)
        if nick in replies:
            l["_status"] = "ответил"
            l["_when"] = replies[nick].get("когда", "")
            l["_reply"] = replies[nick].get("текст", "")
        elif nick in invalid:
            l["_status"], l["_when"] = "мёртвый ник", ""
        elif s and s.get("статус") == "ok":
            l["_status"], l["_when"] = "отправлено", s.get("время", "")
        elif s and s.get("статус") == "fail" and is_permanent(s.get("ошибка", "")):
            l["_status"], l["_when"] = "ошибка", s.get("время", "")
        elif nick in sending:
            l["_status"], l["_when"] = "отправляется", ""
        else:
            l["_status"], l["_when"] = "", ""   # временный fail → снова в очередь (повторим)
        l["_acc"] = s.get("аккаунт", "") if s else ""
        # превью: что реально уйдёт этому человеку (вариант закреплён за ником,
        # чтобы при обновлении страницы текст не прыгал)
        tpl = cell_text(l.get(MSG_COL))
        l["_preview"] = C.render_message(tpl, l, random.Random(nick)) if tpl else ""
        l["_bad"] = C.unknown_fields(tpl, l) if tpl else []
    total = len(leads)
    answered = sum(1 for l in leads if l["_status"] == "ответил")
    done = sum(1 for l in leads if l["_status"] == "отправлено") + answered
    errors = sum(1 for l in leads if l["_status"] in ("ошибка", "мёртвый ник"))
    sending_n = sum(1 for l in leads if l["_status"] == "отправляется")
    sessions = list_sessions()
    limits, today = C.load_limits(), C.sent_today()
    room = C.capacity(sessions, limits, today)

    # фильтр — только на показ; счётчики считаем по всей базе
    f = request.args.get("f", "all")
    keep = {
        "queue": lambda l: l["_status"] in ("", "отправляется"),
        "answered": lambda l: l["_status"] == "ответил",
        "bad": lambda l: l["_status"] in ("ошибка", "мёртвый ник"),
    }.get(f)
    shown_leads = [l for l in leads if keep(l)] if keep else leads

    _plan = {}
    try:
        _plan = json.load(open("data/daily_plan.json", encoding="utf-8"))
    except Exception:
        pass
    return render_template_string(
        MAIN_TPL, leads=shown_leads, total=total, done=done, errors=errors,
        queue=total - done - errors, sending_n=sending_n,
        sessions=sessions, nick_col=NICK_COL, answered=answered,
        f=f if keep else "all", shown=len(shown_leads),
        just=request.args.get("just"),
        today=today, caps={a: C.daily_cap(a, limits) for a in sessions},
        room=room, room_total=sum(room.values()), checking=load_checking(),
        daily_active=bool(_plan.get("active")), daily_target=int(_plan.get("target", 0) or 0),
    )


@app.route("/daily/start", methods=["POST"])
def daily_start():
    try:
        target = max(1, min(int(request.form.get("target", "50")), 500))
    except Exception:
        target = 50
    mode = request.form.get("mode", "personal")
    broadcast = request.form.get("broadcast", "").strip()
    if mode == "broadcast" and broadcast:
        with open("data/broadcast.txt", "w", encoding="utf-8") as fh:
            fh.write(broadcast)
    elif mode == "broadcast" and not broadcast:
        flash("Единый режим выбран, но текст пуст — впиши сообщение.")
        return redirect(url_for("index"))
    json.dump({"target": target, "active": True},
              open("data/daily_plan.json", "w", encoding="utf-8"), ensure_ascii=False)
    _how = "единым текстом" if (mode == "broadcast" and broadcast) else "персонально из базы"
    flash(f"Дневной режим включён: {target} сообщений в день ({_how}), окно 09–21 МСК. "
          f"Растянется автоматически.")
    return redirect(url_for("index", just=1))


@app.route("/daily/stop", methods=["POST"])
def daily_stop():
    try:
        p = json.load(open("data/daily_plan.json", encoding="utf-8"))
    except Exception:
        p = {}
    p["active"] = False
    json.dump(p, open("data/daily_plan.json", "w", encoding="utf-8"), ensure_ascii=False)
    flash("Дневной режим выключен. Что ушло — ушло, остаток ждёт.")
    return redirect(url_for("index"))


@app.route("/settings")
def settings():
    """Второй экран: аккаунты, ключи, журнал отправок."""
    api_id, api_hash = load_config()
    rows = list(reversed(load_log()))   # свежие сверху
    sessions = list_sessions()
    limits, today = C.load_limits(), C.sent_today()
    today_ok = C.sent_today_ok()
    from datetime import datetime as _dt, timedelta as _td
    _frz = spambot.load_freeze()
    frozen = {}
    for _a, _info in _frz.items():
        try:
            _u = _dt.fromisoformat(_info["until"])
            frozen[_a] = {"until_msk": (_u + _td(hours=3)).strftime("%d.%m %H:%M")}
        except Exception:
            frozen[_a] = {"until_msk": "?"}
    return render_template_string(
        SETTINGS_TPL, frozen=frozen, sessions=sessions, proxies=load_proxies(),
        limits=limits, today=today, today_ok=today_ok, default_cap=C.daily_cap("default", limits),
        stats=C.reply_stats(), protected=len(V.protected_files()),
        caps={a: C.daily_cap(a, limits) for a in sessions},
        api_id=api_id or "", api_hash=api_hash or "", rows=rows,
        ok=sum(1 for r in rows if r.get("статус") == "ok"),
        fail=sum(1 for r in rows if r.get("статус") == "fail"),
    )


# старые адреса больше не нужны, но пусть не отдают 404
@app.route("/edit")
def edit():
    return redirect(url_for("index"))


@app.route("/logs")
@app.route("/accounts")
def accounts():
    return redirect(url_for("settings"))


@app.route("/followups")
def followups_page():
    """Вкладка «Фоллоапы»: тексты добивок по базам + аналитика."""
    import stats as S
    return render_template_string(FOLLOWUPS_TPL, rows=S.followup_overview(),
                                  texts=S.followups_text_load(), bases=S.followup_bases(),
                                  day2=3, day3=7)


@app.route("/followups/save", methods=["POST"])
def followups_save():
    import stats as S
    bases = (request.form.get("bases", "") or "").split("|")
    d = S.followups_text_load()
    for i, b in enumerate(bases):
        if not b:
            continue
        t2 = (request.form.get(f"t_{i}_2", "") or "").strip()
        t3 = (request.form.get(f"t_{i}_3", "") or "").strip()
        cur = d.get(b, {})
        cur["2"], cur["3"] = t2, t3
        d[b] = cur
    S.followups_text_save(d)
    flash("Тексты фоллоапов сохранены")
    return redirect(url_for("followups_page"))


# ─── вкладка «Лиды»: лид-движок (lead_engine.py) ─────────────────────────
ENGINE_KINDS = {"discover": "поиск чатов", "collect": "сбор лидов", "export": "выгрузка в рассылку"}
_TG_NICK = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def _engine_back(niche=""):
    return redirect(url_for("engine_page", n=niche))


@app.route("/engine")
def engine_page():
    """Лид-движок: ниши, чаты с рейтингом, сбор и оценка лидов, выгрузка в рассылку."""
    import lead_engine as LE
    from collections import Counter
    c = LE.cfg()
    niches = list(c["niches"].keys())
    cur = request.args.get("n")
    if cur is None:
        cur = niches[0] if niches else ""
    if cur not in c["niches"]:
        cur = ""
    n = c["niches"].get(cur, {"keywords": [], "icp": "", "target": 150})
    chats = LE._load(LE.chats_file(cur), []) if cur else []
    leads = LE._load(LE.leads_file(cur), []) if cur else []

    good = [d for d in leads if not d.get("drop") and d.get("class") == "лпр"
            and (d.get("score") or 0) >= LE.MIN_EXPORT_SCORE]
    f = request.args.get("f", "good" if good else "all")
    shown = good if f == "good" else leads
    shown = sorted(shown, key=lambda d: (bool(d.get("drop")), -(d.get("score") or 0)))[:300]

    lstats = []
    if leads:
        drops = Counter(d["drop"] for d in leads if d.get("drop"))
        cls = Counter(d.get("class") for d in leads if not d.get("drop") and d.get("class"))
        lstats = [("кандидатов", len(leads)),
                  ("🎯 целевых (лпр, ≥%d)" % LE.MIN_EXPORT_SCORE, len(good)),
                  ("уже в рассылке", sum(1 for d in leads if d.get("exported"))),
                  ("лпр / продавцы / мусор", "%d / %d / %d" % (cls.get("лпр", 0), cls.get("продавец", 0), cls.get("мусор", 0))),
                  ("отсеяно фильтрами", ", ".join(f"{k} {v}" for k, v in drops.most_common()) or "0")]

    job = LE._load(LE.JOB, {})
    summ = []
    for k, v in (job.get("summary") or {}).items():
        if isinstance(v, dict):
            v = ", ".join(f"{a}: {b}" for a, b in v.items()) or "—"
        summ.append((k, v))
    return render_template_string(
        ENGINE_TPL, worker=c.get("worker"), niches=niches, cur=cur, n=n,
        kw_text="\n".join(n.get("keywords", [])), chats=chats,
        nsel=sum(1 for r in chats if r.get("selected")), leads=shown, f=f,
        total_leads=len(leads), lstats=lstats,
        ready=sum(1 for d in good if not d.get("exported")),
        job=job, summ=summ, running=LE.busy(), kinds=ENGINE_KINDS)


@app.route("/engine/niche", methods=["POST"])
def engine_niche():
    import lead_engine as LE
    name = (request.form.get("name") or "").strip()[:60]
    old = (request.form.get("old") or "").strip()
    if not name:
        flash("Нужно название ниши")
        return _engine_back(old)
    if LE.busy():
        flash("Движок сейчас работает — сохрани нишу после окончания задачи")
        return _engine_back(old)
    kws = [k.strip() for k in re.split(r"[\n,]+", request.form.get("keywords", "")) if k.strip()]
    icp = (request.form.get("icp") or "").strip()[:1500]
    try:
        target = max(10, min(1000, int(request.form.get("target") or 150)))
    except ValueError:
        target = 150
    c = LE.cfg()
    if old and old != name and old in c["niches"] and name not in c["niches"]:
        c["niches"].pop(old)                       # переименование: переносим и найденное
        for fn in (LE.chats_file, LE.leads_file):
            if os.path.exists(fn(old)):
                os.replace(fn(old), fn(name))
    c["niches"][name] = {"keywords": kws[:LE.MAX_KEYWORDS], "icp": icp, "target": target}
    LE._save(LE.CFG, c)
    flash(f"Ниша «{name}» сохранена")
    return _engine_back(name)


@app.route("/engine/niche/delete", methods=["POST"])
def engine_niche_delete():
    import lead_engine as LE
    name = (request.form.get("name") or "").strip()
    if LE.busy():
        flash("Движок сейчас работает — удалить можно после окончания задачи")
        return _engine_back(name)
    c = LE.cfg()
    if c["niches"].pop(name, None) is not None:
        LE._save(LE.CFG, c)
        for fn in (LE.chats_file, LE.leads_file):
            if os.path.exists(fn(name)):
                os.remove(fn(name))
        flash(f"Ниша «{name}» удалена")
    return _engine_back("")


@app.route("/engine/chats", methods=["POST"])
def engine_chats():
    import lead_engine as LE
    niche = request.form.get("niche", "")
    if niche not in LE.cfg()["niches"]:
        return _engine_back("")
    sel = set(request.form.getlist("sel"))
    rows = LE._load(LE.chats_file(niche), [])
    for r in rows:
        r["selected"] = r["username"] in sel
    add = (request.form.get("add") or "").strip().rstrip("/").split("/")[-1].lstrip("@")
    if add:
        if not _TG_NICK.match(add):
            flash("Не похоже на @username чата")
        elif add.lower() not in {r["username"].lower() for r in rows}:
            rows.insert(0, {"username": add, "title": "", "members": 0, "score": 0,
                            "note": "добавлен вручную", "selected": True})
    LE._save(LE.chats_file(niche), rows)
    flash("Выбор чатов сохранён")
    return _engine_back(niche)


@app.route("/engine/run", methods=["POST"])
def engine_run():
    import time
    import lead_engine as LE
    kind = request.form.get("kind", "")
    niche = request.form.get("niche", "")
    if kind not in ENGINE_KINDS or niche not in LE.cfg()["niches"]:
        return _engine_back(niche)
    if LE.busy():
        flash("Движок уже занят задачей — дождись окончания")
        return _engine_back(niche)
    app_dir = os.path.dirname(os.path.abspath(__file__))
    args = [sys.executable, "lead_engine.py", kind, niche]
    if kind == "export":
        base = (request.form.get("base") or niche).strip()[:60] or niche
        try:
            mn = max(0, min(100, int(request.form.get("min") or 60)))
        except ValueError:
            mn = 60
        subprocess.run(args + [base, "--min", str(mn)], cwd=app_dir, capture_output=True, timeout=180)
        job = LE._load(LE.JOB, {})
        flash(job.get("error") or f"В базу «{base}» добавлено: {(job.get('summary') or {}).get('добавлено', 0)}")
        return _engine_back(niche)
    os.makedirs(os.path.join(app_dir, LE.DIR), exist_ok=True)
    log = open(os.path.join(app_dir, LE.DIR, "last_run.log"), "w")
    subprocess.Popen(args, cwd=app_dir, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(1.5)       # чтобы задача успела занять lock и показаться на странице
    flash(f"Запустил: {ENGINE_KINDS[kind]}. Страница обновляется сама.")
    return _engine_back(niche)


@app.route("/stats")
def stats_page():
    """Вкладка «Статистика»: reply-rate по тексту и по аккаунтам."""
    import stats as S
    return render_template_string(STATS_TPL, funnel=S.funnel(), accs=S.per_account())


@app.route("/inbox")
def inbox():
    """Вкладка «Ответы»: список ответивших лидов."""
    replies = C.load_replies()
    items = sorted(replies.items(), key=lambda kv: kv[1].get("когда", ""), reverse=True)
    return render_template_string(INBOX_TPL, items=items)


@app.route("/inbox/<path:nick>")
def inbox_dialog(nick):
    """Диалог с лидом: история + форма ответа."""
    if not nick.startswith("@"):
        nick = "@" + nick
    replies = C.load_replies()
    info = replies.get(nick, {})
    acc = info.get("аккаунт", "")
    msgs, err = (tg.get_history(acc, nick) if acc else (None, "не знаю, с какого аккаунта писали"))
    return render_template_string(DIALOG_TPL, nick=nick, acc=acc,
                                  msgs=msgs, err=err, info=info, draft="")


@app.route("/inbox/ai_draft", methods=["POST"])
def inbox_ai_draft():
    """Сгенерировать черновик ответа ИИ-продажником и подставить в поле."""
    nick = request.form.get("nick", "").strip()
    acc = request.form.get("acc", "").strip()
    if not nick.startswith("@"):
        nick = "@" + nick
    import ai_sales
    d, needs, aerr = ai_sales.draft(acc, nick)
    if aerr:
        flash("ИИ: " + aerr)
    elif needs:
        flash("⚠️ ИИ считает: тут лучше ответить лично (сложный/горячий лид). Черновик всё равно подставил.")
    replies = C.load_replies()
    info = replies.get(nick, {})
    msgs, herr = (tg.get_history(acc, nick) if acc else (None, "не знаю, с какого аккаунта писали"))
    return render_template_string(DIALOG_TPL, nick=nick, acc=acc,
                                  msgs=msgs, err=herr, info=info, draft=d)


@app.route("/inbox/send", methods=["POST"])
def inbox_send():
    nick = request.form.get("nick", "").strip()
    acc = request.form.get("acc", "").strip()
    text = request.form.get("text", "").strip()
    if not (nick and acc and text):
        flash("Пусто — не отправил")
    else:
        ok, err = tg.send_reply(acc, nick, text)
        flash("Отправлено ✓" if ok else f"Не ушло: {err}")
    return redirect(url_for("inbox_dialog", nick=nick.lstrip("@")))


@app.route("/send", methods=["POST"])
def send():
    sessions = request.form.getlist("sessions")
    if not sessions:
        flash("Отметь хотя бы один аккаунт.")
        return redirect(url_for("index"))
    limit = request.form.get("limit", "5")
    pmin = request.form.get("pause_min", "40")
    pmax = request.form.get("pause_max", "120")
    arg = ",".join(sessions)

    # режим: единое сообщение всем vs персонально из базы
    mode = request.form.get("mode", "personal")
    broadcast = request.form.get("broadcast", "").strip()
    bpath = os.path.join("data", "broadcast.txt")
    if mode == "broadcast" and broadcast:
        with open(bpath, "w", encoding="utf-8") as fh:
            fh.write(broadcast)
    else:
        try:
            os.remove(bpath)          # персональный режим — убираем единый текст
        except OSError:
            pass
        if mode == "broadcast" and not broadcast:
            flash("Единый режим выбран, но текст пуст — вписал бы сообщение.")
            return redirect(url_for("index"))

    subprocess.Popen([sys.executable, "send_campaign.py", arg, str(limit), str(pmin), str(pmax)])
    _how = "единое сообщение всем" if (mode == "broadcast" and broadcast) else "персонально из базы"
    flash(f"Запустил отправку ({_how}): аккаунты [{arg}], до {limit} шт, пауза {pmin}–{pmax} сек.")
    return redirect(url_for("index", just=1))


@app.route("/check/<mode>", methods=["POST"])
def check(mode):
    """Проверка базы (живы ли ники) или ответов. Только чтение, ничего не шлём."""
    if mode not in ("leads", "replies"):
        flash("Неизвестная проверка.")
        return redirect(url_for("index"))
    sessions = list_sessions()
    if not sessions:
        flash("Нужен хотя бы один аккаунт — проверка идёт через Telegram.")
        return redirect(url_for("index"))
    subprocess.Popen([sys.executable, "check.py", mode, ",".join(sessions)])
    flash("Проверка базы запущена: прогоняю ники, ничего не отправляю."
          if mode == "leads" else
          "Смотрю, кто ответил. Обнови страницу через минуту.")
    return redirect(url_for("index"))


@app.route("/leads/save", methods=["POST"])
def leads_save():
    header, data = _read_xlsx()
    n = len(data)
    for i in range(n):
        for c in EDIT_COLS:
            val = request.form.get(f"{c}__{i}")
            if val is not None:
                data[i][c] = val
    save_leads(header, data)
    flash("Изменения сохранены в data/leads.xlsx ✓")
    return redirect(url_for("index"))


@app.route("/limits/save", methods=["POST"])
def limits_save():
    """Дневные потолки: общий и персональный по каждому аккаунту."""
    limits = C.load_limits()
    d = request.form.get("default", "").strip()
    if d.isdigit():
        limits["default"] = int(d)
    for name in list_sessions():
        v = request.form.get("cap__" + name, "").strip()
        if v.isdigit():
            limits[name] = int(v)
        else:
            limits.pop(name, None)   # пусто → берём общий
    C.save_limits(limits)
    flash("Дневные лимиты сохранены. Движок сверяется с ними на каждом запуске.")
    return redirect(url_for("settings"))


@app.route("/leads/add", methods=["POST"])
def leads_add():
    """Добавить контакты вставленным списком: по строке на человека."""
    header, data = _read_xlsx()
    rows, report = C.parse_contacts(request.form.get("contacts", ""),
                                    existing=[cell_text(r.get(NICK_COL)) for r in data])
    if rows:
        # № продолжаем с последнего, остальные колонки оставляем пустыми
        start = 0
        for r in data:
            try:
                start = max(start, int(str(r.get("№", 0)).strip() or 0))
            except ValueError:
                pass
        for i, r in enumerate(rows, 1):
            row = {c: "" for c in header}
            row.update({k: v for k, v in r.items() if k in header})
            if "№" in header:
                row["№"] = start + i
            data.append(row)
        save_leads(header, data)

    parts = [f"Добавлено {report['добавлено']}"]
    if report["дубли"]:
        parts.append(f"пропущено дублей: {len(report['дубли'])}")
    if report["телефоны"]:
        parts.append(f"номеров телефонов: {len(report['телефоны'])} — "
                     f"рассылка работает по никам, не по номерам")
    if report["не понял"]:
        parts.append("не понял строки: " + ", ".join(report["не понял"][:3]))
    flash(". ".join(parts) + ".")
    return redirect(url_for("index"))


@app.route("/lead/delete", methods=["POST"])
def lead_delete():
    nick = request.form.get("del_nick", "").strip()
    header, data = _read_xlsx()
    data = [r for r in data if str(r.get(NICK_COL, "")) != nick]
    save_leads(header, data)
    flash(f"Контакт {nick} удалён из базы.")
    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop():
    # убиваем ТОЛЬКО процессы рассылки — сам сайт (app.py) не трогаем
    subprocess.run(["pkill", "-9", "-f", "send_campaign.py"])
    try:
        json.dump([], open(SENDING, "w", encoding="utf-8"))   # сбросить «отправляется»
    except Exception:
        pass
    flash("Рассылка остановлена. Кто не успел — остался в очереди, повторно им не уйдёт.")
    return redirect(url_for("index"))


@app.route("/account/code", methods=["POST"])
def account_code():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    proxy = request.form.get("proxy", "").strip()
    if not name or not phone:
        flash("Укажи и название, и номер.")
        return redirect(url_for("settings"))
    try:
        start_login(name, phone, proxy)
    except Exception as e:
        flash(f"Не смог отправить код: {e}")
        return redirect(url_for("settings"))
    return render_template_string(CODE_TPL, name=name, need2fa=False)


@app.route("/account/signin", methods=["POST"])
def account_signin():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    password = request.form.get("password", "").strip()

    if password:
        res = finish_login(name, password=password)
    else:
        res = finish_login(name, code=code)

    if res.get("need2fa"):
        return render_template_string(CODE_TPL, name=name, need2fa=True)
    if res.get("error"):
        flash(f"Ошибка входа: {res['error']}")
        return render_template_string(CODE_TPL, name=name, need2fa=False)
    me = res["ok"]
    flash(f"Аккаунт добавлен: {me.first_name or ''} @{me.username or '—'} (сессия {name})")
    return redirect(url_for("settings"))


@app.route("/account/rename", methods=["POST"])
def account_rename():
    old = request.form.get("old", "").strip()
    new = request.form.get("new", "").strip()
    if not new or not re.match(r"^[A-Za-z0-9_]+$", new):
        flash("Новое имя — только латиница, цифры и _ (без пробелов).")
        return redirect(url_for("settings"))
    if new == old:
        return redirect(url_for("settings"))
    old_path = os.path.join(SESS_DIR, old + ".session")
    new_path = os.path.join(SESS_DIR, new + ".session")
    if not os.path.exists(old_path):
        flash(f"Сессия {old} не найдена.")
        return redirect(url_for("settings"))
    if os.path.exists(new_path):
        flash(f"Имя «{new}» уже занято.")
        return redirect(url_for("settings"))
    os.rename(old_path, new_path)
    # переносим и журнал сессии, если есть
    j = os.path.join(SESS_DIR, old + ".session-journal")
    if os.path.exists(j):
        os.rename(j, os.path.join(SESS_DIR, new + ".session-journal"))
    pr = load_proxies()                     # прокси переезжает вместе с именем
    if old in pr:
        pr[new] = pr.pop(old)
        save_proxies(pr)
    accs = load_accounts()                   # и запись о подтверждённости
    if old in accs:
        accs.discard(old)
        accs.add(new)
        save_accounts(accs)
    flash(f"Аккаунт переименован: {old} → {new}")
    return redirect(url_for("settings"))


@app.route("/account/proxy", methods=["POST"])
def account_proxy():
    name = request.form.get("name", "").strip()
    proxy = request.form.get("proxy", "").strip()
    if proxy and not parse_proxy(proxy):
        flash("Прокси в неверном формате. Пример: socks5://user:pass@1.2.3.4:1080")
        return redirect(url_for("settings"))
    pr = load_proxies()
    if proxy:
        pr[name] = proxy
        flash(f"Прокси для {name} сохранён.")
    else:
        pr.pop(name, None)
        flash(f"Прокси у {name} убран.")
    save_proxies(pr)
    return redirect(url_for("settings"))


@app.route("/account/logout", methods=["POST"])
def account_logout():
    name = request.form.get("name", "").strip()
    try:
        logout(name)
        pr = load_proxies()                 # убираем прокси разлогиненного
        if pr.pop(name, None) is not None:
            save_proxies(pr)
        accs = load_accounts()              # и из списка подтверждённых
        accs.discard(name)
        save_accounts(accs)
        flash(f"Аккаунт {name} разлогинен и убран из списка.")
    except Exception as e:
        flash(f"Не смог разлогинить {name}: {e}")
    return redirect(url_for("settings"))


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    # первый запуск: делаем рабочую базу из шаблона
    if not os.path.exists(LEADS) and os.path.exists("data/leads.example.xlsx"):
        import shutil
        shutil.copy("data/leads.example.xlsx", LEADS)
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Дашборд рассылки: {url}\n  (остановить — закрой окно или Ctrl+C)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
