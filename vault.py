#!/usr/bin/env python3
"""
vault.py — шифрование локальных данных паролем.

Что защищаем: файлы сессий (это полный доступ к твоим Telegram-аккаунтам),
api-ключи, базу лидов, логи и ответы. Всё это лежит в data/ обычными файлами:
у кого есть доступ к папке — у того есть доступ к аккаунтам.

Как работает: «Заблокировать» упаковывает файлы в data/vault.enc и удаляет
открытые копии. «Разблокировать» распаковывает обратно.

Честно про границы: пока данные разблокированы, они лежат на диске открыто —
иначе Telethon не сможет работать с сессиями. Защита работает, когда ты
заблокировал папку или выключил компьютер, а не постоянно.
Пароль нигде не хранится: забыл — данные не восстановить.
"""

import os
import io
import glob
import base64
import tarfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

DATA = "data"
VAULT = "data/vault.enc"
MAGIC = b"ASCNV1"
SALT_LEN = 16

# что прячем (относительно data/)
PATTERNS = ("*.session", "*.session-journal", "config.json", "leads.xlsx",
            "sent_log.csv", "sent_text.csv", "replies.json", "invalid.json",
            "proxies.json", "accounts.json", "limits.json", "sending.json")


class VaultError(Exception):
    pass


def _key(password, salt):
    """scrypt: подбор пароля дорогой даже с доступом к файлу.
    Берём из cryptography, а не из hashlib: hashlib.scrypt есть не в каждой
    сборке Python (зависит от того, с каким OpenSSL её собрали)."""
    kdf = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def is_locked():
    return os.path.exists(VAULT)


def protected_files():
    out = []
    for pat in PATTERNS:
        out.extend(sorted(glob.glob(os.path.join(DATA, pat))))
    return [f for f in out if os.path.isfile(f)]


def lock(password):
    """Упаковать и зашифровать. Возвращает список спрятанных файлов."""
    if not password or len(password) < 4:
        raise VaultError("Пароль слишком короткий — минимум 4 символа.")
    if is_locked():
        raise VaultError("Данные уже заблокированы.")
    files = protected_files()
    if not files:
        raise VaultError("Нечего прятать: в data/ нет ни сессий, ни базы.")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in files:
            tar.add(f, arcname=os.path.basename(f))

    salt = os.urandom(SALT_LEN)
    token = Fernet(_key(password, salt)).encrypt(buf.getvalue())
    tmp = VAULT + ".tmp"
    with open(tmp, "wb") as fh:            # сначала целиком, потом подмена —
        fh.write(MAGIC + salt + token)     # иначе сбой оставит битый архив
    os.replace(tmp, VAULT)

    for f in files:                        # открытые копии убираем только теперь
        try:
            os.remove(f)
        except OSError:
            pass
    return files


def unlock(password):
    """Расшифровать и вернуть файлы на место. Возвращает список файлов."""
    if not is_locked():
        raise VaultError("Данные не заблокированы.")
    blob = open(VAULT, "rb").read()
    if not blob.startswith(MAGIC):
        raise VaultError("Файл vault.enc повреждён или от другой версии.")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_LEN]
    token = blob[len(MAGIC) + SALT_LEN:]
    try:
        payload = Fernet(_key(password, salt)).decrypt(token)
    except InvalidToken:
        raise VaultError("Неверный пароль.")

    names = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = os.path.basename(m.name)          # никаких путей наружу
            if not m.isfile() or not name or name.startswith("."):
                continue
            src = tar.extractfile(m)
            if src is None:
                continue
            with open(os.path.join(DATA, name), "wb") as out:
                out.write(src.read())
            names.append(name)
    os.remove(VAULT)
    return names
