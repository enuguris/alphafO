"""Fernet symmetric encryption for secrets stored in DB."""
import base64
import hashlib
from cryptography.fernet import Fernet
from app.config import settings


def _get_fernet() -> Fernet:
    # Derive a 32-byte key from secret_key so no separate key management is needed.
    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
