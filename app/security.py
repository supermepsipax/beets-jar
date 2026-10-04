"""API key generation and verification"""
import hashlib
import re
import secrets

_HASH_RE = re.compile(r"[0-9a-f]{64}")


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def is_valid_hash(value: str) -> bool:
    return bool(_HASH_RE.fullmatch(value))


def verify_api_key(supplied: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_api_key(supplied), stored_hash)
