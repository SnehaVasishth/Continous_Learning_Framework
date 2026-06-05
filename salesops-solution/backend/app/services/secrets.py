"""Fernet-based password encryption.

Key resolution order:
1. EMAIL_SECRET_KEY env var (preferred for cloud deployments — back it with a
   secret manager so it survives restarts and rotations).
2. backend/data/.email_key file (auto-generated for local dev).

Rotating the key invalidates all stored passwords; users would re-add accounts.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..config import DATA

_KEY_PATH = DATA / ".email_key"
_fernet: Fernet | None = None


def _load_key() -> bytes:
    env = os.environ.get("EMAIL_SECRET_KEY")
    if env:
        return env.encode()
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEY_PATH.write_bytes(key)
    try:
        os.chmod(_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _f().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _f().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("decrypt failed — secret key has rotated") from e
