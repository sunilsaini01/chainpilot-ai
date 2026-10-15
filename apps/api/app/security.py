"""Password hashing and login-token helpers. Standard library only.

Passwords: scrypt, a deliberately slow and memory-hard hash, so stolen hashes
are expensive to brute-force. Parameters follow the OWASP Password Storage
Cheat Sheet (N=2^14, r=8, p=5, about 16 MiB of memory per hash) and are
stored inside each hash string, so they can be raised later without breaking
existing passwords.

Tokens: random strings handed to the client once. The database keeps only
their SHA-256 hash, so a database leak does not reveal usable tokens.
"""

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2**14  # CPU/memory cost
SCRYPT_R = 8  # block size
SCRYPT_P = 5  # parallelism
SCRYPT_KEY_LENGTH = 32
SALT_BYTES = 16
TOKEN_BYTES = 32  # 256 bits of randomness

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128  # an upper bound stops someone hashing megabyte-sized "passwords"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=SCRYPT_KEY_LENGTH,
        maxmem=256 * 1024 * 1024,  # allow up to 256 MiB in case parameters are raised later
    )


def hash_password(password: str) -> str:
    """Return a string like ``scrypt$16384$8$5$<salt>$<hash>`` that is safe to store."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash. Returns False for malformed hashes."""
    try:
        algorithm, n, r, p, salt_b64, key_b64 = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected_key = base64.b64decode(key_b64, validate=True)
        actual_key = _scrypt(password, salt, int(n), int(r), int(p))
    # Wrong number of parts, bad base64, bad numbers, or scrypt parameters out of range.
    except (ValueError, OverflowError):
        return False
    # compare_digest takes the same time wherever the bytes differ (no timing leak).
    return hmac.compare_digest(actual_key, expected_key)


# Checked when an email does not exist, so a failed login takes about as long
# either way and response times do not reveal which emails are registered.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def generate_token() -> str:
    """A new random login token (URL-safe text)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 of a token, as stored in the database.

    A fast hash is fine here (unlike passwords): tokens are 256-bit random
    values, so guessing one is infeasible however fast the hash is.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
