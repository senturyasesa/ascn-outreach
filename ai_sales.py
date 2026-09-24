#!/usr/bin/env python3
"""ai_sales.py — ИИ-продажник (Leo) для инбокса. Режим ЧЕРНОВИК:
генерит человечный ответ клиенту по истории диалога, а отправляет его человек
вручную (кнопка «Черновик от ИИ» в диалоге -> текст в поле ответа).

Промпт и база знаний лежат в файлах (правишь текст, не трогая код):
  data/ai_sales_prompt.txt  — роль Leo, стиль, логика продаж
  data/ai_sales_kb.md       — факты, тарифы, возражения
  data/ai_sales.json        — модель/температура/ключ
Ключ OpenRouter переиспользуем из data/rewrite.json, если в ai_sales.json пусто.
"""

import os
import json
import urllib.request

import tg
import campaign as C

os.chdir(os.path.dirname(os.path.abspath(__file__)))

CFG = "data/ai_sales.json"
PROMPT = "data/ai_sales_prompt.txt"
KB = "data/ai_sales_kb.md"
BROADCAST = "data/broadcast.txt"
REPLIES = "data/replies.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
HUMAN_MARK = "[НУЖЕН ЧЕЛОВЕК]"
MAX_TURNS = 14          # сколько последних сообщений диалога отдаём модели


def _cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    if not c.get("key"):
        try:
            c["key"] = json.load(open("data/rewrite.json", encoding="utf-8")).get("key", "")
        except Exception:
            c["key"] = ""
    return c


def _read(p):
    try:
        return open(p, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _system():
    s = _read(PROMPT)
    bc = _read(BROADCAST)
    if bc:
        s += ("\n\n=== НАШЕ ПЕРВОЕ (ХОЛОДНОЕ) СООБЩЕНИЕ, НА КОТОРОЕ ЛИД ОТВЕТИЛ ===\n"
              "С этого началась переписка. Это то, что мы предложили человеку, "
              "держи в голове контекст разговора:\n" + bc)
    kb = _read(KB)
    if kb:
        s += "\n\n=== БАЗА ЗНАНИЙ (факты, цены, тарифы, только отсюда) ===\n" + kb
    return s


def _convo(acc, nick):
    """История диалога в формате чата: наши сообщения -> assistant, лид -> user."""
    msgs, _ = tg.get_history(acc, nick, limit=MAX_TURNS)
    convo = []
    for m in (msgs or []):
        t = (m.get("text") or "").strip()
        if t:
            convo.append({"role": "assistant" if m.get("out") else "user", "content": t})
    if convo:
        return convo[-MAX_TURNS:]
    # фолбэк: хотя бы последний ответ лида из replies.json
    try:
        rep = json.load(open(REPLIES, encoding="utf-8"))
        info = rep.get(nick) or rep.get("@" + str(nick).lstrip("@"))
        if isinstance(info, dict) and (info.get("текст") or "").strip():
            return [{"role": "user", "content": info["текст"].strip()}]
    except Exception:
        pass
    return []


def draft(acc, nick):
    """-> (текст_черновика, нужен_человек: bool, ошибка|None)."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return "", False, "ИИ-продажник выключен (data/ai_sales.json: enabled=false)"
    if not cfg.get("key"):
        return "", False, "нет ключа OpenRouter (data/ai_sales.json или rewrite.json)"

    convo = _convo(acc, nick)
    if not convo:
        return "", False, "нет истории диалога для контекста (обнови страницу)"

    messages = [{"role": "system", "content": _system()}] + convo
    try:
        body = json.dumps({
            "model": cfg.get("model", "anthropic/claude-3.5-sonnet"),
            "messages": messages,
            "temperature": cfg.get("temperature", 0.7),
        }).encode("utf-8")
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": "Bearer " + cfg["key"],
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 45)) as resp:
            data = json.load(resp)
        out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        return "", False, f"ИИ не ответил ({type(e).__name__})"

    if not out:
        return "", False, "пустой ответ ИИ"
    out = C.strip_long_dashes(out)
    needs = out.startswith(HUMAN_MARK)
    if needs:
        out = out[len(HUMAN_MARK):].strip()
    return out, needs, None


_CLASSES = ("интерес", "отказ", "негатив", "бот", "другое")


def classify_reply(text):
    """Классифицировать ответ лида: интерес / отказ / негатив / бот / другое.
    -> одно слово из _CLASSES (или 'другое' при ошибке)."""
    text = (text or "").strip()
    if not text:
        return "другое"
    cfg = _cfg()
    if not cfg.get("key"):
        return "другое"
    sysmsg = (
        "Ты классифицируешь ответ лида на холодную рассылку по автоматизации через ИИ. "
        "Категории (верни РОВНО одно слово):\n"
        "интерес — хочет узнать больше, спрашивает цену/как работает, готов на созвон, позитив;\n"
        "отказ — не интересно, не актуально, вежливое нет;\n"
        "негатив — грубость, агрессия, претензия «откуда мои контакты», мат;\n"
        "бот — автоответчик, реклама в ответ, не по теме нашего продукта;\n"
        "другое — непонятно/нейтрально.\n"
        "Верни только одно слово из: интерес, отказ, негатив, бот, другое.")
    try:
        body = json.dumps({
            "model": "openai/gpt-4o-mini",   # дёшево, для классификации хватает
            "messages": [{"role": "system", "content": sysmsg},
                         {"role": "user", "content": text[:500]}],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": "Bearer " + cfg["key"],
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 30)) as resp:
            data = json.load(resp)
        out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip().lower()
        for c in _CLASSES:
            if c in out:
                return c
        return "другое"
    except Exception as e:
        print("classify_reply err:", type(e).__name__)
        return "другое"


def generate_followup(stage, base=""):
    """Сгенерировать текст ДОБИВКИ (касание 2/3) для неответивших лидов.
    Один текст на базу/стадию за прогон (followup.py его кэширует и рерайтит per-лид).
    -> текст или "" при ошибке/выключенном ключе."""
    cfg = _cfg()
    if not cfg.get("key"):
        return ""
    bc = _read(BROADCAST)
    role = ("касание №2: мягкое, ненавязчивое напоминание о себе"
            if int(stage) == 2 else
            "касание №3: финальное, в духе «если сейчас не актуально, просто скажите»")
    sysmsg = (
        "Ты менеджер ASCN, пишешь ДОБИВКУ в холодной Telegram-переписке лиду"
        + (f" из сегмента «{base}»" if base and base != "default" else "")
        + ", который не ответил на первое сообщение. "
        f"Задача: {role}. 1-2 коротких предложения, на «вы», живо и по-человечески, "
        "без длинных и коротких тире, без продающих штампов. Не повторяй дословно первое "
        "сообщение, не представляйся заново, мягко веди на короткий созвон и закончи вопросом. "
        "Верни ТОЛЬКО текст сообщения, без пояснений и кавычек.")
    user = (f"Первое сообщение, на которое лид не ответил:\n{bc}"
            if bc else "Первое сообщение было предложением автоматизации через ИИ-агентов ASCN.")
    try:
        body = json.dumps({
            "model": cfg.get("model", "openai/gpt-4o"),
            "messages": [{"role": "system", "content": sysmsg},
                         {"role": "user", "content": user}],
            "temperature": 0.8,
        }).encode("utf-8")
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": "Bearer " + cfg["key"],
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 45)) as resp:
            data = json.load(resp)
        out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        return C.strip_long_dashes(out) if out else ""
    except Exception as e:
        print("generate_followup err:", type(e).__name__)
        return ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "followup":
        st = sys.argv[2] if len(sys.argv) > 2 else "2"
        bs = sys.argv[3] if len(sys.argv) > 3 else ""
        print(generate_followup(st, bs))
    else:
        a, n = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("", "")
        txt, human, err = draft(a, n)
        print("НУЖЕН ЧЕЛОВЕК:" if human else "черновик:", err or "")
        print(txt)
