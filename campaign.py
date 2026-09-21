#!/usr/bin/env python3
"""
campaign.py — «как именно мы шлём»: текст сообщения, темп, лимиты, устройства.

Три независимых части, каждая проверяема отдельно:
  render_message  — подстановка полей базы и выбор варианта текста
  дневные лимиты  — сколько ушло с аккаунта за сутки и можно ли ещё
  пауза/устройство — темп по времени суток и стабильный профиль клиента
"""

import os
import csv
import json
import random
import hashlib
import re
import urllib.request
from datetime import datetime

LIMITS = "data/limits.json"      # {"default": 10, "akk1": 5}
DEFAULT_DAILY = 10               # README: 5-10 в день на аккаунт
LOG = "data/sent_log.csv"
REWRITE_CFG = "data/rewrite.json"   # настройки AI-рерайта (ключ, модель, промпт)


# ─── 1. текст сообщения ────────────────────────────────────────────────
def _pick(variants, rnd):
    return rnd.choice(variants) if variants else ""


def render_message(template, lead, rnd=None, return_choices=False):
    """{имя} → значение колонки базы, {привет|здравствуйте} → один из вариантов.

    Внутри фигурных скобок есть «|» — это выбор варианта.
    Иначе — имя колонки из xlsx (регистр не важен).
    Неизвестная колонка остаётся как есть: в превью сразу видно опечатку.

    return_choices=True — вернуть ещё и какие варианты выпали: по ним потом
    считается reply rate, то есть какой текст реально работает.
    """
    rnd = rnd or random
    cols = {str(k).strip().lower(): ("" if v is None else str(v)) for k, v in (lead or {}).items()}
    out, choices, i = [], [], 0
    while i < len(template):
        ch = template[i]
        if ch != "{":
            out.append(ch)
            i += 1
            continue
        end = template.find("}", i)
        if end == -1:                      # незакрытая скобка — оставляем текстом
            out.append(template[i:])
            break
        body = template[i + 1:end]
        if "|" in body:
            pick = _pick([v.strip() for v in body.split("|")], rnd)
            choices.append(pick)
            out.append(pick)
        else:
            key = body.strip().lower()
            out.append(cols[key] if key in cols else "{" + body + "}")
        i = end + 1
    text = "".join(out).strip()
    return (text, choices) if return_choices else text


def unknown_fields(template, lead):
    """Какие {поля} в шаблоне не нашлись в базе — для предупреждения в UI."""
    cols = {str(k).strip().lower() for k in (lead or {})}
    bad, i = [], 0
    while True:
        i = template.find("{", i)
        if i == -1:
            return bad
        end = template.find("}", i)
        if end == -1:
            return bad
        body = template[i + 1:end]
        if "|" not in body and body.strip().lower() not in cols:
            bad.append(body.strip())
        i = end + 1


# ─── 2. дневные лимиты по аккаунтам ────────────────────────────────────
def load_limits():
    if os.path.exists(LIMITS):
        try:
            return json.load(open(LIMITS, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_limits(d):
    json.dump(d, open(LIMITS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def daily_cap(acc, limits=None):
    limits = load_limits() if limits is None else limits
    try:
        return max(0, int(limits.get(acc, limits.get("default", DEFAULT_DAILY))))
    except (TypeError, ValueError):
        return DEFAULT_DAILY


def sent_today(day=None, log=LOG):
    """{аккаунт: сколько попыток ушло за сутки}. Считаем и fail тоже:
    для Telegram это всё равно был запрос."""
    day = day or datetime.now().strftime("%Y-%m-%d")
    counts = {}
    if not os.path.exists(log):
        return counts
    for r in csv.DictReader(open(log, encoding="utf-8-sig")):
        if str(r.get("время", "")).startswith(day):
            acc = r.get("аккаунт") or ""
            if acc:
                counts[acc] = counts.get(acc, 0) + 1
    return counts


def sent_today_ok(day=None, log=LOG):
    """{аккаунт: сколько ДОСТАВЛЕНО (ok) за сутки} — без фейлов."""
    day = day or datetime.now().strftime("%Y-%m-%d")
    counts = {}
    if not os.path.exists(log):
        return counts
    for r in csv.DictReader(open(log, encoding="utf-8-sig")):
        if str(r.get("время", "")).startswith(day) and r.get("статус") == "ok":
            acc = r.get("аккаунт") or ""
            if acc:
                counts[acc] = counts.get(acc, 0) + 1
    return counts


def remaining(acc, limits=None, today=None):
    today = sent_today() if today is None else today
    return max(0, daily_cap(acc, limits) - today.get(acc, 0))


def capacity(accounts, limits=None, today=None):
    """Сколько всего можно отправить прямо сейчас по всем аккаунтам."""
    today = sent_today() if today is None else today
    limits = load_limits() if limits is None else limits
    return {a: remaining(a, limits, today) for a in accounts}


# ─── 3. темп и устройство ──────────────────────────────────────────────
# днём люди пишут быстрее, ночью почти не пишут — множитель к паузе
_HOUR_FACTOR = [
    2.5, 2.5, 2.5, 2.5, 2.5, 2.5,   # 00-05 глухая ночь
    2.0, 1.6, 1.2, 1.0, 1.0, 1.0,   # 06-11 утро, рабочий ритм
    1.1, 1.0, 1.0, 1.0, 1.0, 1.1,   # 12-17 день
    1.2, 1.3, 1.5, 1.8, 2.2, 2.5,   # 18-23 вечер
]


def pause_seconds(pause_min, pause_max, hour=None, rnd=None):
    """Пауза между сообщениями с поправкой на время суток."""
    rnd = rnd or random
    hour = datetime.now().hour if hour is None else hour
    lo, hi = min(pause_min, pause_max), max(pause_min, pause_max)
    return int(round(rnd.randint(lo, hi) * _HOUR_FACTOR[hour % 24]))


def typing_seconds(text, rnd=None):
    """Сколько «печатать» перед отправкой: примерно как человек, но не вечно.
    Разброс применяем до границ, иначе он же их и пробивает."""
    rnd = rnd or random
    return round(min(8.0, max(1.5, len(text or "") / 22.0 * rnd.uniform(0.8, 1.2))), 1)


# у каждого аккаунта свой стабильный профиль клиента: сессия и правда
# отдельное устройство, и Telegram незачем видеть их как один браузер
_DEVICES = [
    ("iPhone 14", "iOS 17.5.1"), ("iPhone 13 mini", "iOS 16.7.8"),
    ("Samsung SM-S911B", "Android 14"), ("Xiaomi 23021RAA2Y", "Android 13"),
    ("Google Pixel 7", "Android 14"), ("iPhone 12", "iOS 17.4"),
]


_APP_VERSIONS = ("10.9.2", "10.9.1", "10.8.3", "11.0.0", "10.12.0")


def device_for(acc):
    """Один и тот же аккаунт всегда получает один и тот же профиль.
    Моделей мало, поэтому различаем ещё версией приложения и патчем системы —
    иначе на семи аккаунтах профили начинают совпадать."""
    h = int(hashlib.sha256(("ascn:" + str(acc)).encode("utf-8")).hexdigest(), 16)
    model, system = _DEVICES[h % len(_DEVICES)]
    return {
        "device_model": model,
        "system_version": "%s.%d" % (system, (h // 7) % 9),
        "app_version": _APP_VERSIONS[(h // 97) % len(_APP_VERSIONS)],
    }


# ─── 4. reply rate: что из этого вообще работает ───────────────────────
REPLIES = "data/replies.json"
SENT_TEXT = "data/sent_text.csv"
INVALID = "data/invalid.json"


def load_replies(path=REPLIES):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {}


def load_invalid(path=INVALID):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _rate(replied, sent):
    return round(100.0 * replied / sent) if sent else 0


def reply_stats(replies=None, sent_text=SENT_TEXT):
    """Сколько ответили: всего, по аккаунтам и по вариантам текста.
    Вариант — то, что выпало из {а|б}: так видно, какая формулировка заходит."""
    replies = load_replies() if replies is None else replies
    rows = []
    if os.path.exists(sent_text):
        try:
            rows = list(csv.DictReader(open(sent_text, encoding="utf-8-sig")))
        except Exception:
            rows = []
    by_acc, by_var = {}, {}
    for r in rows:
        nick = r.get("ник", "")
        answered = nick in replies
        for key, bucket in ((r.get("аккаунт", "") or "—", by_acc),
                            (r.get("вариант", "") or "без вариантов", by_var)):
            b = bucket.setdefault(key, {"отправлено": 0, "ответили": 0})
            b["отправлено"] += 1
            b["ответили"] += bool(answered)
    for bucket in (by_acc, by_var):
        for b in bucket.values():
            b["процент"] = _rate(b["ответили"], b["отправлено"])
    total = len(rows)
    return {
        "отправлено": total,
        "ответили": sum(1 for r in rows if r.get("ник", "") in replies),
        "процент": _rate(sum(1 for r in rows if r.get("ник", "") in replies), total),
        "по аккаунтам": by_acc,
        "по вариантам": dict(sorted(by_var.items(), key=lambda kv: -kv[1]["процент"])),
    }


# ─── 5. добавление контактов списком ──────────────────────────────────
_NICK_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{3,31}$")
_PHONE_RE = re.compile(r"^\+?\d[\d\s()-]{6,}$")


def normalize_nick(raw):
    """@ivan, ivan, t.me/ivan, https://t.me/ivan → @ivan. Мусор → None."""
    v = (raw or "").strip()
    if not v:
        return None
    for pref in ("https://", "http://", "www."):
        if v.lower().startswith(pref):
            v = v[len(pref):]
    for pref in ("t.me/", "telegram.me/"):
        if v.lower().startswith(pref):
            v = v[len(pref):]
    v = v.split("?")[0].strip().rstrip("/")
    if not v.startswith("@"):
        v = "@" + v
    return v if _NICK_RE.match(v) else None


def parse_contacts(text, existing=()):
    """Разбирает вставленный список. Одна строка — один контакт:

        @ivan
        @ivan<TAB>Иван<TAB>нет лидов<TAB>Привет, {имя}!

    Разделитель — табуляция (так вставляется из таблицы) или «;».
    Возвращает (строки, отчёт): что добавили, что пропустили и почему.
    """
    have = {str(n).strip().lower() for n in existing}
    rows, dup, bad, phones = [], [], [], []
    seen = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else (
            line.split(";") if ";" in line else [line])
        parts = [x.strip() for x in parts]
        nick = normalize_nick(parts[0])
        if not nick:
            (phones if _PHONE_RE.match(parts[0]) else bad).append(parts[0][:40])
            continue
        key = nick.lower()
        if key in have or key in seen:
            dup.append(nick)
            continue
        seen.add(key)
        rows.append({
            "ник": nick,
            "имя": parts[1] if len(parts) > 1 else "",
            "главная боль": parts[2] if len(parts) > 2 else "",
            "сообщение для захода": parts[3] if len(parts) > 3 else "",
        })
    return rows, {"добавлено": len(rows), "дубли": dup, "не понял": bad, "телефоны": phones}


# ─── AI-рерайт сообщения (OpenRouter) ──────────────────────────────────
# Единый текст (broadcast) прогоняем через дешёвую модель для уникализации,
# чтобы Telegram не видел 300 одинаковых сообщений. Длинные тире вычищаем
# ВСЕГДА (Денис их не выносит), даже если рерайт выключен или упал.

_LONG_DASHES = ("—", "–", "―", "‒", "⸺", "⸻")


def strip_long_dashes(text):
    """Меняем любые длинные тире на запятую и подчищаем артефакты."""
    if not text:
        return text
    for d in _LONG_DASHES:
        text = text.replace(" %s " % d, ", ")   # « слово — слово » -> «слово, слово»
        text = text.replace(d, ", ")            # прочие вхождения
    text = re.sub(r"\s+,", ",", text)           # пробел перед запятой
    text = re.sub(r"(,\s*){2,}", ", ", text)    # двойные запятые
    text = re.sub(r"[ \t]{2,}", " ", text)      # двойные пробелы
    return text.strip().strip(",").strip()


def load_rewrite_cfg():
    try:
        return json.load(open(REWRITE_CFG, encoding="utf-8"))
    except Exception:
        return {}


def rewrite(text, broadcast=False):
    """Рерайт единого текста через OpenRouter. Персональные тексты не трогаем.
    При любой ошибке/таймауте/выключенном рерайте — возвращаем оригинал.
    Длинные тире чистятся в любом случае (и до, и после рерайта)."""
    text = strip_long_dashes(text)
    cfg = load_rewrite_cfg()
    if not broadcast or not cfg.get("enabled") or not cfg.get("key"):
        return text
    try:
        body = json.dumps({
            "model": cfg.get("model", "deepseek/deepseek-chat"),
            "messages": [
                {"role": "system", "content": cfg.get("prompt", "")},
                {"role": "user", "content": text},
            ],
            "temperature": cfg.get("temperature", 0.9),
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={"Authorization": "Bearer " + cfg["key"],
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 20)) as resp:
            data = json.load(resp)
        out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        return strip_long_dashes(out) if out else text
    except Exception as e:
        print("    рерайт не сработал (%s), шлю оригинал" % type(e).__name__)
        return text
