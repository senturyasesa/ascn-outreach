#!/usr/bin/env python3
"""
api.py — REST API для управления рассылкой из ASCN Агента.
Все методы GET (агент умеет только GET), защита токеном в query (?token=...).
Ответы — плоский JSON.
"""

import os
import csv
import sys
import json
import glob
import subprocess
from functools import wraps

from flask import Blueprint, request, jsonify

bp = Blueprint("api", __name__)

DATA = "data"
LOG = "data/sent_log.csv"
SENDING = "data/sending.json"
ACCOUNTS = "data/accounts.json"
LEADS = "data/leads.xlsx"
TOKEN_FILE = "data/api_token.txt"


def _token():
    try:
        return open(TOKEN_FILE, encoding="utf-8").read().strip()
    except Exception:
        return ""


def require_token(f):
    @wraps(f)
    def w(*a, **k):
        tok = _token()
        if not tok or request.args.get("token", "") != tok:
            return jsonify({"success": False, "error": "invalid or missing token",
                            "code": "AUTH"}), 403
        return f(*a, **k)
    return w


def _load_json(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _sessions():
    confirmed = set(_load_json(ACCOUNTS, []))
    files = set(os.path.basename(s)[:-8] for s in glob.glob(os.path.join(DATA, "*.session")))
    return sorted(confirmed & files) if confirmed else sorted(files)


def _running():
    return subprocess.run(["pgrep", "-f", "send_campaign.py"],
                          capture_output=True).returncode == 0


def _sent_stats():
    ok = fail = 0
    if os.path.exists(LOG):
        try:
            for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
                st = r.get("статус") or r.get("status")
                if st == "ok":
                    ok += 1
                elif st == "fail":
                    fail += 1
        except Exception:
            pass
    return ok, fail


def _leads_count():
    try:
        import openpyxl
        ws = openpyxl.load_workbook(LEADS).active
        return sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, 3).value)
    except Exception:
        return 0


@bp.route("/api/status")
@require_token
def api_status():
    ok, fail = _sent_stats()
    plan = _daily_plan()
    return jsonify({
        "status": "running" if _running() else "idle",
        "accounts": _sessions(),
        "total_accounts": len(_sessions()),
        "leads_total": _leads_count(),
        "sent_ok": ok,
        "sent_failed": fail,
        "sending_now": len(_load_json(SENDING, [])),
        "daily_active": plan["active"],
        "daily_target": plan["target"],
        "daily_service_up": _daily_running(),
    })


@bp.route("/api/accounts")
@require_token
def api_accounts():
    return jsonify({"success": True, "accounts": _sessions(),
                    "total": len(_sessions())})


@bp.route("/api/start")
@require_token
def api_start():
    if _running():
        return jsonify({"success": False, "error": "campaign already running",
                        "code": "BUSY"})
    accs = _sessions()
    if not accs:
        return jsonify({"success": False, "error": "no logged-in accounts",
                        "code": "NO_ACCOUNTS"})
    try:
        count = max(1, min(int(request.args.get("count", 5)), 100))
    except Exception:
        count = 5
    _msg = request.args.get("message", "").strip()
    if _msg:
        open("data/broadcast.txt", "w", encoding="utf-8").write(_msg)
    else:
        try:
            os.remove("data/broadcast.txt")
        except OSError:
            pass
    subprocess.Popen([sys.executable, "send_campaign.py", ",".join(accs),
                      str(count), "90", "240"])
    return jsonify({
        "success": True,
        "message": f"campaign started: up to {count} messages across {len(accs)} accounts",
        "accounts": accs,
        "count": count,
    })


@bp.route("/api/stop")
@require_token
def api_stop():
    subprocess.run(["pkill", "-9", "-f", "send_campaign.py"])
    try:
        json.dump([], open(SENDING, "w", encoding="utf-8"))
    except Exception:
        pass
    return jsonify({"success": True, "message": "campaign stopped"})


@bp.route("/api/add_lead")
@require_token
def api_add_lead():
    nick = request.args.get("nick", "").strip()
    pain = request.args.get("pain", "").strip()
    message = request.args.get("message", "").strip()
    if not nick:
        return jsonify({"success": False, "error": "nick required", "code": "NO_NICK"})
    if not nick.startswith("@"):
        nick = "@" + nick
    try:
        import openpyxl
        wb = openpyxl.load_workbook(LEADS)
        ws = wb.active
        header = [str(ws.cell(1, c).value or "") for c in range(1, ws.max_column + 1)]
        row = []
        for h in header:
            if h == "ник":
                row.append(nick)
            elif h == "главная боль":
                row.append(pain)
            elif h == "сообщение для захода":
                row.append(message)
            elif h == "№":
                row.append(ws.max_row)
            else:
                row.append("")
        ws.append(row)
        wb.save(LEADS)
        total = sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, 3).value)
        return jsonify({"success": True, "message": f"lead {nick} added",
                        "leads_total": total})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "code": "ERR"})


@bp.route("/api/add_leads")
@require_token
def api_add_leads():
    """Добавить пачку ников за раз: ?nicks=@a,@b @c
    Разделители — запятая, пробел, перенос строки. Дубли пропускаются.
    Ники без персонального текста → шлём им в режиме единого сообщения."""
    import re
    raw = request.args.get("nicks", "").strip()
    parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
    nicks = []
    for p in parts:
        n = p if p.startswith("@") else "@" + p
        if n not in nicks:
            nicks.append(n)
    if not nicks:
        return jsonify({"success": False, "error": "nicks required", "code": "NO_NICKS"})
    try:
        import openpyxl
        wb = openpyxl.load_workbook(LEADS)
        ws = wb.active
        header = [str(ws.cell(1, c).value or "") for c in range(1, ws.max_column + 1)]
        try:
            nick_idx = header.index("ник") + 1
        except ValueError:
            return jsonify({"success": False, "error": "no 'ник' column", "code": "NO_COL"})
        existing = set()
        for r in range(2, ws.max_row + 1):
            v = ws.cell(r, nick_idx).value
            if v:
                existing.add(str(v).strip())
        added, skipped = [], []
        for nick in nicks:
            if nick in existing:
                skipped.append(nick)
                continue
            row = []
            for h in header:
                if h == "ник":
                    row.append(nick)
                elif h == "№":
                    row.append(ws.max_row)
                else:
                    row.append("")
            ws.append(row)
            existing.add(nick)
            added.append(nick)
        wb.save(LEADS)
        total = sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, nick_idx).value)
        return jsonify({
            "success": True,
            "message": f"added {len(added)}, skipped {len(skipped)} (already in base)",
            "added": added,
            "added_count": len(added),
            "skipped": skipped,
            "skipped_count": len(skipped),
            "leads_total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "code": "ERR"})


# ─────────────── ДНЕВНОЙ ПЛАНИРОВЩИК ───────────────
DAILY_PLAN = "data/daily_plan.json"


def _daily_plan():
    try:
        p = json.load(open(DAILY_PLAN, encoding="utf-8"))
        return {"target": int(p.get("target", 0)), "active": bool(p.get("active", False))}
    except Exception:
        return {"target": 0, "active": False}


def _daily_running():
    return subprocess.run(["pgrep", "-f", "daily_sender.py"],
                          capture_output=True).returncode == 0


@bp.route("/api/start_daily")
@require_token
def api_start_daily():
    """Запустить дневной план: count сообщений в день, растянуть по окну 09-21 МСК.
    С message — единый текст всем; без — персональный из базы."""
    if not _sessions():
        return jsonify({"success": False, "error": "no logged-in accounts",
                        "code": "NO_ACCOUNTS"})
    try:
        target = max(1, min(int(request.args.get("count", 50)), 500))
    except Exception:
        target = 50
    msg = request.args.get("message", "").strip()
    if msg:
        open("data/broadcast.txt", "w", encoding="utf-8").write(msg)
    json.dump({"target": target, "active": True},
              open(DAILY_PLAN, "w", encoding="utf-8"), ensure_ascii=False)
    return jsonify({
        "success": True,
        "message": f"daily plan started: up to {target}/day across {len(_sessions())} accounts, window 09-21 MSK",
        "target": target,
        "mode": "broadcast" if msg else "personal",
    })


@bp.route("/api/stop_daily")
@require_token
def api_stop_daily():
    try:
        p = json.load(open(DAILY_PLAN, encoding="utf-8"))
    except Exception:
        p = {}
    p["active"] = False
    json.dump(p, open(DAILY_PLAN, "w", encoding="utf-8"), ensure_ascii=False)
    return jsonify({"success": True, "message": "daily plan stopped"})


@bp.route("/api/report")
@require_token
def api_report():
    """Готовый текст вечернего отчёта — агент дёргает по расписанию и пересылает."""
    import datetime
    import openpyxl
    utc_today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    ok = fail = 0
    by_acc = {}
    done = set()
    if os.path.exists(LOG):
        for r in csv.DictReader(open(LOG, encoding="utf-8-sig")):
            st = r.get("статус")
            if st == "ok":
                done.add(r["ник"])
            if str(r.get("время", ""))[:10] == utc_today:
                if st == "ok":
                    ok += 1
                    a = r.get("аккаунт", "")
                    by_acc[a] = by_acc.get(a, 0) + 1
                elif st == "fail":
                    fail += 1
    replies = _load_json("data/replies.json", {})
    try:
        ws = openpyxl.load_workbook(LEADS).active
        tot = sum(1 for r in range(2, ws.max_row + 1) if ws.cell(r, 3).value)
    except Exception:
        tot = 0
    plan = _daily_plan()
    lines = ["Отчёт по рассылке ASCN"]
    lines.append(f"Отправлено сегодня: {ok} из {plan['target']}")
    if fail:
        lines.append(f"Не прошло попыток: {fail} (обошли другими акками)")
    lines.append(f"Ответили всего: {len(replies)}")
    lines.append(f"База: {len(done)}/{tot} отправлено, осталось {tot - len(done)}")
    if by_acc:
        lines.append("По аккаунтам: " + ", ".join(
            f"{a}:{n}" for a, n in sorted(by_acc.items(), key=lambda x: -x[1])))
    report = "\n".join(lines)
    return jsonify({
        "success": True, "report": report,
        "sent_today": ok, "failed_today": fail, "replies_total": len(replies),
        "target": plan["target"], "base_total": tot,
        "base_done": len(done), "base_left": tot - len(done),
    })
