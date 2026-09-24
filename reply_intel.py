#!/usr/bin/env python3
"""reply_intel.py — классификация ответов лидов по намерению.

Класс хранится ОТДЕЛЬНО в data/reply_class.json ({ник: {класс, sig}}), чтобы
переписывание replies.json скриптом check.py не затирало теги. Переклассифицирует,
если текст ответа изменился (лид написал новое). Вызывается из notify_replies.
"""
import os
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import ai_sales

REPLIES = "data/replies.json"
CLASSES = "data/reply_class.json"


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def classify_all(force=False):
    reps = _load(REPLIES, {})
    store = _load(CLASSES, {})
    n = 0
    for nick, info in reps.items():
        if not isinstance(info, dict):
            continue
        txt = info.get("текст", "") or ""
        sig = txt[:60]
        cur = store.get(nick)
        if not force and isinstance(cur, dict) and cur.get("sig") == sig:
            continue
        store[nick] = {"класс": ai_sales.classify_reply(txt), "sig": sig}
        n += 1
    if n:
        json.dump(store, open(CLASSES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return n


def load_classes():
    """ник -> класс (плоско, для аналитики)."""
    s = _load(CLASSES, {})
    return {k: (v.get("класс") if isinstance(v, dict) else v) for k, v in s.items()}


if __name__ == "__main__":
    import sys
    print("классифицировано:", classify_all(force="--force" in sys.argv))
