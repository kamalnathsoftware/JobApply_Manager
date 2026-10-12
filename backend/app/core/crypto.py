"""Fernet encryption for site credentials and Playwright storage_state at rest."""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CryptoError(Exception):
    pass


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise CryptoError("FERNET_KEY is not configured")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise CryptoError("cannot decrypt (wrong FERNET_KEY or corrupt data)") from e
