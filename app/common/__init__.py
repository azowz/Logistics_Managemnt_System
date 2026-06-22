"""Shared, business-agnostic primitives used across the Mesaar backend.

This package contains small, dependency-light building blocks (time helpers,
pagination contracts, response envelopes) that are safe to import from any
layer without creating cycles. It intentionally contains NO business logic.
"""

from __future__ import annotations

__all__: list[str] = []
