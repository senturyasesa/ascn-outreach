#!/usr/bin/env python3
"""api_server.py — только REST API для агента на отдельном порту (по умолчанию 8766).

Порт открыт наружу, чтобы облачный агент достучался с любого IP, но КАЖДЫЙ метод
требует токен (api.require_token). Дашборд здесь не отдаётся — он на 8765,
закрыт файрволом под владельца.
"""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
import api

app = Flask(__name__)
app.register_blueprint(api.bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("API_PORT", "8766")), debug=False, threaded=True)
