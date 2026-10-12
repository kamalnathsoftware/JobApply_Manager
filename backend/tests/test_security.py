import pytest

from app.core.crypto import CryptoError, decrypt, encrypt
from app.core.security import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("hunter2hunter2")
    assert h != "hunter2hunter2"
    assert verify_password("hunter2hunter2", h)
    assert not verify_password("nope", h)


def test_fernet_roundtrip_and_tamper():
    token = encrypt('{"cookie": "secret"}')
    assert "secret" not in token
    assert decrypt(token) == '{"cookie": "secret"}'
    with pytest.raises(CryptoError):
        decrypt(token[:-4] + "AAAA")
