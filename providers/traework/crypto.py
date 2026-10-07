"""Decrypt TraeWork storage.json iCubeAuthInfo blobs.

Algorithm matches official TRAE SOLO CN 0.1.56 `byteCrypto.js`:
magic `tc\\x05\\x10\\x00\\x00`, AES-128-CBC, SHA-512 checksum.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from credential_crypto import CredentialCryptoError

_MAGIC = b"tc\x05\x10\x00\x00"
_HEADER = 6
_KEY_LEN = 32
_HASH_LEN = 64

# Official client XOR tables (ure ^ dre) used as SHA-512 salt.
_URE = bytes(
    [
        82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
        124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
        84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
        8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
    ]
)
_DRE = bytes(
    [
        31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
        96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
        160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
        23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
    ]
)
_SALT = bytes(a ^ b for a, b in zip(_URE, _DRE))


def decrypt_tc_b64(value: str) -> str:
    if not value or not isinstance(value, str):
        raise CredentialCryptoError("TraeWork auth blob is empty")
    try:
        blob = base64.b64decode(value)
    except Exception as exc:
        raise CredentialCryptoError("TraeWork auth blob is not base64") from exc
    if not blob.startswith(_MAGIC):
        raise CredentialCryptoError("TraeWork auth blob is not tc AES")
    key_mat = blob[_HEADER : _HEADER + _KEY_LEN]
    cipher = blob[_HEADER + _KEY_LEN :]
    if len(key_mat) != _KEY_LEN or not cipher or len(cipher) % 16:
        raise CredentialCryptoError("TraeWork auth blob is truncated")
    mixed = hashlib.sha512(key_mat).digest() + _SALT
    derived = hashlib.sha512(mixed).digest()
    aes_key, iv = derived[:16], derived[16:32]
    decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(cipher) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    try:
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise CredentialCryptoError("TraeWork auth blob padding is invalid") from exc
    checksum, body = plain[:_HASH_LEN], plain[_HASH_LEN:]
    if hashlib.sha512(body).digest() != checksum:
        raise CredentialCryptoError("TraeWork auth blob checksum failed")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialCryptoError("TraeWork auth blob is not UTF-8") from exc
