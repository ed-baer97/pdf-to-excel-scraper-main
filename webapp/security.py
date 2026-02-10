import base64
import os

from cryptography.fernet import Fernet


def _get_fernet(key: str) -> Fernet:
    if not key:
        # Derive a stable dev key if not provided (NOT for production).
        raw = os.getenv("SECRET_KEY", "dev-secret-key-change-me").encode("utf-8")
        key = base64.urlsafe_b64encode(raw[:32].ljust(32, b"0")).decode("utf-8")
    return Fernet(key)


def encrypt_password(plain: str, key: str) -> bytes:
    return _get_fernet(key).encrypt(plain.encode("utf-8"))


def decrypt_password(token: bytes | None, key: str) -> str:
    if not token:
        return ""
    return _get_fernet(key).decrypt(token).decode("utf-8")

