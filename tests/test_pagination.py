"""Unit tests for pagination models (app.common.pagination).

Covers:
* PageParams defaults, bounds, limit/offset derived properties.
* Page.create() — item set, total, page count (including edge cases).

No database or network access is required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.common.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams


# ---------------------------------------------------------------------------
# PageParams — defaults
# ---------------------------------------------------------------------------


def test_page_params_default_page_is_1() -> None:
    p = PageParams()
    assert p.page == 1


def test_page_params_default_size_is_default_page_size() -> None:
    p = PageParams()
    assert p.size == DEFAULT_PAGE_SIZE


def test_page_params_limit_equals_size() -> None:
    p = PageParams(size=25)
    assert p.limit == 25


def test_page_params_offset_page_1_is_zero() -> None:
    p = PageParams(page=1, size=50)
    assert p.offset == 0


def test_page_params_offset_page_2() -> None:
    p = PageParams(page=2, size=50)
    assert p.offset == 50


def test_page_params_offset_page_3() -> None:
    p = PageParams(page=3, size=10)
    assert p.offset == 20


def test_page_params_offset_formula() -> None:
    for page in range(1, 6):
        size = 20
        p = PageParams(page=page, size=size)
        assert p.offset == (page - 1) * size


# ---------------------------------------------------------------------------
# PageParams — bounds validation
# ---------------------------------------------------------------------------


def test_page_params_page_must_be_at_least_1() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(page=0)


def test_page_params_size_must_be_at_least_1() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(size=0)


def test_page_params_size_must_not_exceed_max_page_size() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(size=MAX_PAGE_SIZE + 1)


def test_page_params_size_exactly_max_is_accepted() -> None:
    p = PageParams(size=MAX_PAGE_SIZE)
    assert p.size == MAX_PAGE_SIZE


def test_page_params_large_page_number_is_accepted() -> None:
    p = PageParams(page=10_000, size=1)
    assert p.page == 10_000


# ---------------------------------------------------------------------------
# Page.create — standard scenarios
# ---------------------------------------------------------------------------


def test_page_create_returns_page_instance() -> None:
    params = PageParams(page=1, size=10)
    result = Page.create(items=list(range(10)), total=100, params=params)
    assert isinstance(result, Page)


def test_page_create_correct_items() -> None:
    items = ["a", "b", "c"]
    result = Page.create(items=items, total=50, params=PageParams(page=1, size=3))
    assert result.items == items


def test_page_create_correct_total() -> None:
    result = Page.create(items=[], total=42, params=PageParams())
    assert result.total == 42


def test_page_create_correct_page() -> None:
    result = Page.create(items=[], total=10, params=PageParams(page=3, size=5))
    assert result.page == 3


def test_page_create_correct_size() -> None:
    result = Page.create(items=[], total=10, params=PageParams(page=1, size=7))
    assert result.size == 7


def test_page_create_pages_ceiling_division() -> None:
    """11 items at 5 per page → 3 pages (ceiling division)."""
    result = Page.create(items=[], total=11, params=PageParams(page=1, size=5))
    assert result.pages == 3


def test_page_create_pages_exact_division() -> None:
    """10 items at 5 per page → exactly 2 pages."""
    result = Page.create(items=[], total=10, params=PageParams(page=1, size=5))
    assert result.pages == 2


def test_page_create_one_item_one_page() -> None:
    result = Page.create(items=["x"], total=1, params=PageParams(page=1, size=50))
    assert result.pages == 1


# ---------------------------------------------------------------------------
# Page.create — zero total
# ---------------------------------------------------------------------------


def test_page_create_zero_total_yields_zero_pages() -> None:
    result = Page.create(items=[], total=0, params=PageParams())
    assert result.pages == 0


def test_page_create_zero_total_empty_items() -> None:
    result = Page.create(items=[], total=0, params=PageParams())
    assert result.items == []


# ---------------------------------------------------------------------------
# Page — generic type safety
# ---------------------------------------------------------------------------


def test_page_is_generic() -> None:
    """Page[str] and Page[int] should be constructable without errors."""
    str_page = Page[str].create(
        items=["hello", "world"], total=2, params=PageParams()
    )
    int_page = Page[int].create(items=[1, 2, 3], total=3, params=PageParams())
    assert str_page.items == ["hello", "world"]
    assert int_page.items == [1, 2, 3]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_default_page_size_is_positive() -> None:
    assert DEFAULT_PAGE_SIZE > 0


def test_max_page_size_is_positive() -> None:
    assert MAX_PAGE_SIZE > 0


def test_max_page_size_greater_than_default() -> None:
    assert MAX_PAGE_SIZE >= DEFAULT_PAGE_SIZE
