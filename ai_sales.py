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


if __name__ == "__main__":
    import sys
    a, n = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("", "")
    txt, human, err = draft(a, n)
    print("НУЖЕН ЧЕЛОВЕК:" if human else "черновик:", err or "")
    print(txt)
