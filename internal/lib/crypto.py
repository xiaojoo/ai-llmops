import base64
import hashlib

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def build_master_key(secret: str) -> bytes:
    """32 字节主密钥：SHA256(secret)。"""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_value(plain: str, master_key: bytes) -> str:
    """AES-CBC 加密明文，返回 base64(iv + ciphertext)。"""
    iv = __import__("os").urandom(16)
    cipher = Cipher(algorithms.AES(master_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ct).decode("utf-8")


def decrypt_value(encoded: str, master_key: bytes) -> str:
    """解密 base64(iv + ciphertext)；失败返回原文（兼容未加密旧数据）。"""
    try:
        raw = base64.b64decode(encoded)
        iv, ct = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(master_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    except Exception:
        return encoded
