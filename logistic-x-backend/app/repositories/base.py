"""Shared plumbing for domain repositories.

Repositories never commit or roll back: the calling service owns the unit of
work (flush → append domain events → commit). Reads are tenant-scoped by
PostgreSQL Row-Level Security, so these helpers add no ``tenant_id`` filter;
services still verify ``obj.tenant_id`` where an id comes from the client.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.repositories.errors import NotFoundError


def coerce_uuid(value: Union[str, uuid.UUID, None]) -> Optional[uuid.UUID]:
    """Return ``value`` as a ``uuid.UUID``, or ``None`` when it is not a valid id.

    Lets ``get_by_id`` treat a malformed path id as "not found" instead of
    raising a 500 from the database driver.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class BaseRepository:
    """No-commit create/get/update/soft-delete for a single model.

    Subclasses set :attr:`model`. ``update`` ignores ``None`` values so PATCH
    payloads only change the fields that were sent.
    """

    model: Any = None

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, **data):
        obj = self.model(**data)
        self._session.add(obj)
        return obj

    def update(self, obj, **data):
        for field, value in data.items():
            if value is not None:
                setattr(obj, field, value)
        return obj

    def get_by_id(self, obj_id: Union[str, uuid.UUID]):
        oid = coerce_uuid(obj_id)
        if oid is None:
            return None
        return self._session.get(self.model, oid)

    def get_by_id_or_raise(self, obj_id: Union[str, uuid.UUID]):
        obj = self.get_by_id(obj_id)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} {obj_id} not found.")
        return obj

    def soft_delete(self, obj, *, deleted_by: Optional[uuid.UUID] = None):
        obj.soft_delete()
        obj.deleted_by = deleted_by
        return obj

    def restore(self, obj):
        obj.restore()
        obj.deleted_by = None
        return obj


__all__ = ["BaseRepository", "coerce_uuid"]
