#!/usr/bin/env python3
"""
errors_map.py — классификация ошибок Telegram. Общая для движка и дашборда,
чтобы «постоянная ошибка» значила одно и то же в обоих местах.

Смотрим ТИП исключения, а не текст: текст у Telethon человекочитаемый и слова
«flood» в нём нет вообще —
    FloodWaitError → «A wait of 3600 seconds is required»
    PeerFloodError → «Too many requests»
"""

from telethon import errors

# ── лид не примет сообщение никогда: повторять бессмысленно ─────────────
LEAD_PERMANENT = (
    errors.UserPrivacyRestrictedError,   # закрыт настройками приватности
    errors.UserIsBlockedError,           # заблокировал нас
    errors.YouBlockedUserError,          # мы заблокировали его
    errors.InputUserDeactivatedError,    # аккаунт лида удалён
    errors.UsernameNotOccupiedError,     # ника не существует
    errors.UsernameInvalidError,
    errors.PeerIdInvalidError,
    errors.UserBotError,
    errors.ChatWriteForbiddenError,
    errors.PremiumAccountRequiredError,  # принимает только от Premium
)

# ── наш аккаунт слать больше не может: снимаем с ротации ────────────────
ACCOUNT_DEAD = (
    errors.PeerFloodError,               # спам-блок: Telegram пометил аккаунт
    errors.FloodWaitError,               # лимит запросов исчерпан
    errors.SlowModeWaitError,
    errors.UserDeactivatedError,         # наш аккаунт удалён
    errors.UserDeactivatedBanError,      # наш аккаунт забанен
    errors.AuthKeyUnregisteredError,     # сессия отозвана
    errors.SessionRevokedError,
    errors.SessionExpiredError,
)

# get_entity на несуществующий ник отдаёт ValueError, а не RPC-ошибку
_VALUE_ERROR_TEXTS = ("no user has", "cannot find any entity",
                      "could not find the input entity")

# логи прежней версии писались без имени класса — узнаём их по тексту
_LEGACY_TEXTS = (
    "privacy_premium_required", "premium_required", "user_privacy_restricted",
    "privacy settings do not allow",
    "user is blocked",
    "you blocked this user",
    "the specified user was deleted",
    "the username is not in use",
    "nobody is using this username",
    "an invalid peer was used",
    "you can't write in this chat",
    "allow_payment_required",   # получатель требует оплату Stars за входящие
)


def err_code(e):
    """Как ошибка ложится в лог: «ИмяКласса: текст».
    По имени класса её потом однозначно узнаёт дашборд."""
    return f"{type(e).__name__}: {e}"


def is_account_dead(e):
    """Аккаунт исчерпан/заблокирован — убрать из ротации (лид не виноват)."""
    return isinstance(e, ACCOUNT_DEAD)


def is_permanent_exc(e):
    """Лиду больше не пишем никогда."""
    if isinstance(e, LEAD_PERMANENT):
        return True
    if isinstance(e, ValueError):
        return any(k in str(e).lower() for k in _VALUE_ERROR_TEXTS)
    if "ALLOW_PAYMENT_REQUIRED" in str(e):
        return True   # получатель принимает только платные сообщения
    return False


_PERMANENT_CODES = tuple(c.__name__.lower() for c in LEAD_PERMANENT)


def is_permanent(err):
    """То же, но по строке из лога (лог читаем при следующем запуске)."""
    e = (err or "").lower()
    return (any(k in e for k in _PERMANENT_CODES)
            or any(k in e for k in _VALUE_ERROR_TEXTS)
            or any(k in e for k in _LEGACY_TEXTS))


def cell_text(v):
    """Ячейка Excel → строка. Числа/даты/None не роняют рассылку."""
    return "" if v is None else str(v).strip()
