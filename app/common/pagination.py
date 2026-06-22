"""Generic, business-agnostic pagination contracts.

``PageParams`` is intended to be used as a FastAPI dependency (via
``Depends(PageParams)``) so that every list endpoint exposes a uniform
``?page=&size=`` interface. ``Page[T]`` is the matching response envelope.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

__all__ = ["PageParams", "Page", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE"]

# A type variable for the item payload carried by a :class:`Page`.
T = TypeVar("T")

# Sensible defaults/limits shared by every paginated endpoint.
DEFAULT_PAGE_SIZE: int = 50
MAX_PAGE_SIZE: int = 200


class PageParams(BaseModel):
    """Inbound pagination parameters (1-based pages, bounded size).

    Designed to be used as a FastAPI dependency. Pydantic performs the bounds
    validation, so handlers can trust ``page``/``size`` without re-checking.
    """

    page: int = Field(default=1, ge=1, description="1-based page number.")
    size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page (1..200).",
    )

    @property
    def limit(self) -> int:
        """SQL ``LIMIT`` value (equal to the requested page size)."""

        return self.size

    @property
    def offset(self) -> int:
        """SQL ``OFFSET`` value derived from the 1-based page number."""

        return (self.page - 1) * self.size


class Page(BaseModel, Generic[T]):
    """A single page of results plus the metadata needed to navigate them."""

    items: list[T] = Field(default_factory=list, description="The page payload.")
    total: int = Field(ge=0, description="Total number of matching records.")
    page: int = Field(ge=1, description="The 1-based page number returned.")
    size: int = Field(ge=1, description="The page size used for this result.")
    pages: int = Field(ge=0, description="Total number of available pages.")

    @classmethod
    def create(cls, items: list[T], total: int, params: PageParams) -> "Page[T]":
        """Build a :class:`Page` from raw items, a total count, and the params.

        Args:
            items: The records belonging to the current page.
            total: The total number of matching records (across all pages).
            params: The pagination parameters that produced ``items``.

        Returns:
            A fully populated :class:`Page` instance with a computed page count.
        """

        # Ceiling division so a partial final page still counts as one page.
        # ``total == 0`` yields ``pages == 0`` (no pages to navigate).
        pages = (total + params.size - 1) // params.size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=pages,
        )
