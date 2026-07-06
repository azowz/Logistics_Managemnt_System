"""Cryptographic utilities for the Integrations & Webhooks context (Sprint 13).

Three concerns, deliberately separated:

* **API keys** — a caller credential. We store only a one-way ``bcrypt`` hash
  (via the shared password context) plus a non-secret ``key_prefix`` for display
  and O(1) lookup. The plaintext is shown exactly once, at create/rotate.
* **Outbound webhook signing** — HMAC-SHA256 over the exact request body using a
  per-subscription *shared secret*. Because signing needs the secret value (a hash
  is one-way and useless here), the secret is stored **encrypted at rest** with
  Fernet (key derived from ``settings.secret_key``) and decrypted only to sign.
  It is shown once at create/rotate and never returned by read APIs.
* **Inbound verification** — the partner signs their request body with the *plaintext
  API key* they were issued; we verify using the key they present on the request
  (which we also authenticate against the stored hash), so no second secret store is
  needed. All comparisons use ``hmac.compare_digest`` (constant-time).

The Fernet-at-rest key is derived from ``SECRET_KEY`` here; a dedicated KMS-managed
key is the recommended hardening follow-up (see docs/27 known risks).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Tuple

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.security import pwd_context

# Public prefix scheme for issued API keys: ``mesaar_<prefix>_<secret>``.
_KEY_NAMESPACE = "mesaar"
_PREFIX_BYTES = 6  # → 8 base32-ish chars, safe to display/store in the clear
_SECRET_BYTES = 32  # 256 bits of entropy for the secret portion
_WEBHOOK_SECRET_BYTES = 32


# --- API keys ---------------------------------------------------------------


def generate_api_key() -> Tuple[str, str, str]:
    """Return ``(plaintext, key_prefix, key_hash)`` for a freshly minted API key.

    ``plaintext`` is returned to the caller exactly once. ``key_prefix`` is safe to
    persist/display; ``key_hash`` is the bcrypt hash stored at rest.
    """
    prefix = secrets.token_hex(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    plaintext = f"{_KEY_NAMESPACE}_{prefix}_{secret}"
    return plaintext, prefix, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    """One-way hash of an API key for at-rest storage (bcrypt via the shared context)."""
    return pwd_context.hash(plaintext)


def verify_api_key(plaintext: str, key_hash: str) -> bool:
    """Constant-time verification of a presented API key against its stored hash."""
    if not plaintext or not key_hash:
        return False
    try:
        return pwd_context.verify(plaintext, key_hash)
    except (ValueError, TypeError):
        return False


def extract_key_prefix(plaintext: str) -> str | None:
    """Pull the public ``key_prefix`` out of a ``mesaar_<prefix>_<secret>`` key."""
    parts = (plaintext or "").split("_")
    if len(parts) < 3 or parts[0] != _KEY_NAMESPACE:
        return None
    return parts[1]


# --- Fernet secret-at-rest (outbound webhook secrets) -----------------------


def _fernet() -> Fernet:
    """Fernet built from a key deterministically derived from ``SECRET_KEY``."""
    raw = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def generate_webhook_secret() -> str:
    """Return a fresh plaintext webhook signing secret (shown once at create/rotate)."""
    return f"whsec_{secrets.token_urlsafe(_WEBHOOK_SECRET_BYTES)}"


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a webhook secret for at-rest storage (reversible, so we can sign)."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str | None:
    """Decrypt a stored webhook secret; ``None`` if it cannot be decrypted."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


# --- HMAC signing / verification --------------------------------------------


def compute_signature(secret: str, body: str, *, timestamp: str | None = None) -> str:
    """Return ``sha256=<hexdigest>`` HMAC-SHA256 over ``[timestamp.]body``.

    When ``timestamp`` is provided it is prefixed as ``{timestamp}.{body}`` so the
    signature also binds the send time (enabling a replay window on verification).
    """
    signing_input = f"{timestamp}.{body}" if timestamp else body
    digest = hmac.new(
        secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str, body: str, signature: str, *, timestamp: str | None = None
) -> bool:
    """Constant-time verification of an HMAC-SHA256 signature over ``[timestamp.]body``."""
    if not secret or not signature:
        return False
    expected = compute_signature(secret, body, timestamp=timestamp)
    return hmac.compare_digest(expected, signature)


__all__ = [
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
    "extract_key_prefix",
    "generate_webhook_secret",
    "encrypt_secret",
    "decrypt_secret",
    "compute_signature",
    "verify_signature",
]
