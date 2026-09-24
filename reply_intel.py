#!/usr/bin/env python3
"""reply_intel.py — классификация ответов лидов по намерению.

Тэг (интерес/отказ/негатив/бот/другое) пишется в data/replies.json[nick]["класс"].
Классифицирует только новые ответы (без класса). Вызывается из notify_replies
после проверки ответов, так что тэги проставляются сами.
"""
import os
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import ai_sales

REPLIES = "data/replies.json"


def classify_all(force=False):
    try:
        d = json.load(open(REPLIES, encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for nick, info in d.items():
        if not isinstance(info, dict):
            continue
        if not force and info.get("класс"):
            continue
        info["класс"] = ai_sales.classify_reply(info.get("текст", ""))
        n += 1
    if n:
        json.dump(d, open(REPLIES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return n


if __name__ == "__main__":
    import sys
    print("классифицировано:", classify_all(force="--force" in sys.argv))
