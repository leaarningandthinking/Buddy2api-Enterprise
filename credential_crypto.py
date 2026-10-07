"""Encryption helpers for account credentials stored in SQLite."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


PREFIX = "enc:v1:"
_FERNET_PREFIX = PREFIX + "fernet:"
_DPAPI_PREFIX = PREFIX + "dpapi:"
_cipher_lock = threading.Lock()
_fernet: Fernet | None = None
_fernet_source: tuple[str, str] | None = None


class CredentialCryptoError(RuntimeError):
    """Raised when encrypted credentials cannot be protected or recovered."""


def is_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(PREFIX))


def _key_file(db_path: Path) -> Path:
    configured = os.environ.get("CB_GATEWAY_CREDENTIAL_KEY_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return db_path.with_suffix(db_path.suffix + ".credentials.key")


def _load_or_create_file_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = path.read_bytes().strip()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes().strip()
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key + b"\n")
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    try:
        Fernet(key)
    except (TypeError, ValueError) as exc:
        raise CredentialCryptoError(f"Invalid credential key file: {path}") from exc
    return key


def _get_fernet(db_path: Path) -> Fernet:
    global _fernet, _fernet_source

    configured = os.environ.get("CB_GATEWAY_MASTER_KEY", "")
    if configured:
        source = ("env", hashlib.sha256(configured.encode("utf-8")).hexdigest())
    else:
        path = _key_file(db_path).resolve(strict=False)
        source = ("file", str(path))

    with _cipher_lock:
        if _fernet is not None and _fernet_source == source:
            return _fernet
        if configured:
            key = base64.urlsafe_b64encode(hashlib.sha256(configured.encode("utf-8")).digest())
        else:
            key = _load_or_create_file_key(path)
        _fernet = Fernet(key)
        _fernet_source = source
        return _fernet


def _dpapi_encrypt(data: bytes) -> bytes:
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_char)))
    output = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_wchar_p, ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)):
        raise CredentialCryptoError(f"DPAPI encryption failed with error {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_char)))
    output = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)):
        raise CredentialCryptoError(f"DPAPI decryption failed with error {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def encrypt_secret(value: str | None, db_path: Path) -> str:
    if not value or is_encrypted(value):
        return value or ""
    raw = value.encode("utf-8")
    # Always Fernet (MASTER_KEY or sidecar key file). Linux Docker cannot open
    # Windows DPAPI rows; existing enc:v1:dpapi: values still decrypt on Windows.
    token = _get_fernet(db_path).encrypt(raw).decode("ascii")
    return _FERNET_PREFIX + token


def decrypt_secret(value: str | None, db_path: Path) -> str:
    if not value:
        return ""
    if not is_encrypted(value):
        return value
    try:
        if value.startswith(_DPAPI_PREFIX):
            if os.name != "nt":
                raise CredentialCryptoError("DPAPI-protected credentials can only be opened on Windows")
            protected = base64.urlsafe_b64decode(value[len(_DPAPI_PREFIX):].encode("ascii"))
            return _dpapi_decrypt(protected).decode("utf-8")
        if value.startswith(_FERNET_PREFIX):
            token = value[len(_FERNET_PREFIX):].encode("ascii")
            return _get_fernet(db_path).decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise CredentialCryptoError("Stored credentials could not be decrypted; check the configured master key") from exc
    raise CredentialCryptoError("Unsupported credential encryption format")


def reset_cache() -> None:
    """Clear cached key material after configuration changes or in tests."""
    global _fernet, _fernet_source
    with _cipher_lock:
        _fernet = None
        _fernet_source = None
