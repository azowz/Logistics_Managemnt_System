"""Celery worker package for the Mesaar logistics platform.

This package hosts the configured Celery application and the task modules
executed by background workers. Importing :data:`app.workers.celery_app`
yields a fully configured :class:`celery.Celery` instance.
"""

from __future__ import annotations

from app.workers.celery_app import celery_app

__all__ = ["celery_app"]
