"""Repository-level exceptions for CRUD operations."""

from __future__ import annotations


class RepositoryError(Exception):
    """Base exception for repository failures."""


class NotFoundError(RepositoryError):
    """Raised when an entity cannot be located by identifier."""
