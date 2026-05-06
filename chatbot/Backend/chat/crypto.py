"""Symmetric encryption for UserMeta secrets.

Uses Fernet (AES-128-CBC + HMAC). Key is loaded from
`settings.CHAT_FERNET_KEY` (a urlsafe-base64 32-byte key) or, in DEBUG, derived
from `SECRET_KEY` so dev environments don't need extra config.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _derive_key() -> bytes:
    raw = getattr(settings, "CHAT_FERNET_KEY", None)
    if raw:
        if isinstance(raw, str):
            raw = raw.encode()
        return raw
    # Dev fallback: derive deterministically from SECRET_KEY.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""
