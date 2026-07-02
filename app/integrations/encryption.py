"""Secret-encryption provider boundary for webhook signing secrets (Sprint 14).

Sprint 13 encrypted webhook secrets inline with a ``SECRET_KEY``-derived Fernet key.
Sprint 14 formalizes that behind a small port so a KMS-managed provider can be swapped
in cleanly for production without touching the service:

* :class:`SecretEncryptionProvider` — the port (``encrypt`` / ``decrypt`` + ``provider_name``
  / ``key_id`` metadata persisted alongside the ciphertext for auditability + rotation).
* :class:`LocalFernetSecretProvider` — the default, wrapping the existing Fernet helper.
* KMS — **documented as a production deployment requirement**; not faked here. A real
  ``KmsSecretProvider`` would implement the same port against the deployment's KMS.

Decrypt failures return ``None`` (never raise, never leak) so the caller can fail safe
(see integration_service.py — a delivery is never signed with an empty secret).
"""

from __future__ import annotations

import hashlib
from typing import Optional, Protocol, runtime_checkable

from app.core.config import get_settings
from app.integrations import crypto


@runtime_checkable
class SecretEncryptionProvider(Protocol):
    """Reversible at-rest encryption for signing secrets (needed to sign outbound)."""

    provider_name: str

    @property
    def key_id(self) -> str: ...

    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> Optional[str]: ...


class LocalFernetSecretProvider:
    """Default provider: Fernet with a key derived from ``SECRET_KEY``.

    ``key_id`` is a short, non-reversible fingerprint of the active key so a key change
    (e.g. ``SECRET_KEY`` rotation) is detectable in stored metadata. Suitable for
    single-key deployments; a KMS-backed provider is the production hardening path.
    """

    provider_name = "local_fernet"

    @property
    def key_id(self) -> str:
        digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).hexdigest()
        return f"fernet:{digest[:16]}"

    def encrypt(self, plaintext: str) -> str:
        return crypto.encrypt_secret(plaintext)

    def decrypt(self, ciphertext: str) -> Optional[str]:
        return crypto.decrypt_secret(ciphertext)


_provider: SecretEncryptionProvider = LocalFernetSecretProvider()


def get_secret_provider() -> SecretEncryptionProvider:
    """Return the process-wide secret-encryption provider (DI seam / test override)."""
    return _provider


def set_secret_provider(provider: SecretEncryptionProvider) -> None:
    """Override the process-wide secret-encryption provider (deployment/tests)."""
    global _provider
    _provider = provider


__all__ = [
    "SecretEncryptionProvider",
    "LocalFernetSecretProvider",
    "get_secret_provider",
    "set_secret_provider",
]
