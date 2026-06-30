"""Notifications & Communications API routes (thin handlers, RBAC).

Literal paths are declared before dynamic ``{id}`` paths so they take precedence.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.pagination import Page
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import NotificationChannel, NotificationStatus, UserRole
from app.schemas.notification import (
    NotificationCancelRequest,
    NotificationCreate,
    NotificationDeliveryAttemptRead,
    NotificationListParams,
    NotificationRead,
    NotificationTemplateCreate,
    NotificationTemplateListParams,
    NotificationTemplateRead,
    NotificationTemplateUpdate,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

_WRITE = (UserRole.ADMIN, UserRole.MANAGER)
_READ = (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT, UserRole.DRIVER)
_TENANT_WIDE = (UserRole.ADMIN, UserRole.MANAGER)  # see their tenant's notifications


def _viewer_scope(current_user):
    """Return the user id a non-privileged viewer is restricted to, else ``None``.

    ADMIN/MANAGER get tenant-wide visibility; CLIENT/DRIVER are scoped to the
    notifications addressed to them (per-user ownership, beyond RLS tenant isolation).
    """
    return None if current_user.role in _TENANT_WIDE else current_user.id


def _tpl_page(p) -> Page[NotificationTemplateRead]:
    return Page[NotificationTemplateRead](items=[NotificationTemplateRead.model_validate(x) for x in p.items],
                                          total=p.total, page=p.page, size=p.size, pages=p.pages)


def _ntf_page(p) -> Page[NotificationRead]:
    return Page[NotificationRead](items=[NotificationRead.model_validate(x) for x in p.items],
                                  total=p.total, page=p.page, size=p.size, pages=p.pages)


# ============================ Templates ============================


@router.post("/templates", response_model=NotificationTemplateRead, status_code=status.HTTP_201_CREATED,
             summary="Create a notification template.")
def create_template(payload: NotificationTemplateCreate, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_WRITE))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(NotificationService(session).create_template(**payload.model_dump()))


@router.get("/templates/search", response_model=Page[NotificationTemplateRead], summary="Search templates.")
def search_templates(
    q: Optional[str] = Query(default=None, max_length=256),
    channel: Optional[NotificationChannel] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[NotificationTemplateRead]:
    params = NotificationTemplateListParams(q=q, channel=channel, event_type=event_type, active=active,
                                            include_deleted=include_deleted, sort_by=sort_by, sort_dir=sort_dir,
                                            page=page, size=size)
    return _tpl_page(NotificationService(session).list_templates(params))


@router.get("/templates", response_model=Page[NotificationTemplateRead], summary="List templates.")
def list_templates(
    channel: Optional[NotificationChannel] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[NotificationTemplateRead]:
    params = NotificationTemplateListParams(channel=channel, event_type=event_type, active=active,
                                            include_deleted=include_deleted, sort_by=sort_by, sort_dir=sort_dir,
                                            page=page, size=size)
    return _tpl_page(NotificationService(session).list_templates(params))


@router.get("/templates/{template_id}", response_model=NotificationTemplateRead, summary="Get a template.")
def get_template(template_id: uuid.UUID, include_deleted: bool = Query(default=False),
                 session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(NotificationService(session).get_template(template_id, include_deleted=include_deleted))


@router.patch("/templates/{template_id}", response_model=NotificationTemplateRead, summary="Update a template.")
def update_template(template_id: uuid.UUID, payload: NotificationTemplateUpdate, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(*_WRITE))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(
        NotificationService(session).update_template(template_id, **payload.model_dump(exclude_unset=True)))


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft-delete a template.")
def delete_template(template_id: uuid.UUID, session: Session = Depends(get_session),
                    current_user=Depends(require_roles(UserRole.ADMIN))):
    NotificationService(session).delete_template(template_id)


@router.post("/templates/{template_id}/restore", response_model=NotificationTemplateRead, summary="Restore a template.")
def restore_template(template_id: uuid.UUID, session: Session = Depends(get_session),
                     current_user=Depends(require_roles(UserRole.ADMIN))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(NotificationService(session).restore_template(template_id))


@router.post("/templates/{template_id}/activate", response_model=NotificationTemplateRead, summary="Activate a template.")
def activate_template(template_id: uuid.UUID, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(NotificationService(session).activate_template(template_id))


@router.post("/templates/{template_id}/deactivate", response_model=NotificationTemplateRead, summary="Deactivate a template.")
def deactivate_template(template_id: uuid.UUID, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_WRITE))) -> NotificationTemplateRead:
    return NotificationTemplateRead.model_validate(NotificationService(session).deactivate_template(template_id))


# ============================ Notifications ============================


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED, summary="Create a notification.")
def create_notification(payload: NotificationCreate, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_WRITE))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).create_notification(**payload.model_dump(by_alias=False)))


@router.get("/search", response_model=Page[NotificationRead], summary="Search notifications.")
def search_notifications(
    q: Optional[str] = Query(default=None, max_length=256),
    status_filter: Optional[NotificationStatus] = Query(default=None, alias="status"),
    channel: Optional[NotificationChannel] = Query(default=None),
    recipient_user_id: Optional[uuid.UUID] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    unread_only: bool = Query(default=False),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[NotificationRead]:
    scope = _viewer_scope(current_user)
    params = NotificationListParams(q=q, status=status_filter, channel=channel,
                                    recipient_user_id=scope or recipient_user_id,
                                    event_type=event_type, unread_only=unread_only, include_deleted=include_deleted,
                                    sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _ntf_page(NotificationService(session).list_notifications(params))


@router.get("/unread", response_model=Page[NotificationRead], summary="List the current user's unread notifications.")
def list_unread(page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
                session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> Page[NotificationRead]:
    return _ntf_page(NotificationService(session).list_unread(current_user.id, page=page, size=size))


@router.get("", response_model=Page[NotificationRead], summary="List notifications.")
def list_notifications(
    status_filter: Optional[NotificationStatus] = Query(default=None, alias="status"),
    channel: Optional[NotificationChannel] = Query(default=None),
    recipient_user_id: Optional[uuid.UUID] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    unread_only: bool = Query(default=False),
    include_deleted: bool = Query(default=False),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ)),
) -> Page[NotificationRead]:
    scope = _viewer_scope(current_user)
    params = NotificationListParams(status=status_filter, channel=channel,
                                    recipient_user_id=scope or recipient_user_id,
                                    event_type=event_type, unread_only=unread_only, include_deleted=include_deleted,
                                    sort_by=sort_by, sort_dir=sort_dir, page=page, size=size)
    return _ntf_page(NotificationService(session).list_notifications(params))


@router.get("/{notification_id}", response_model=NotificationRead, summary="Get a notification.")
def get_notification(notification_id: uuid.UUID, include_deleted: bool = Query(default=False),
                     session: Session = Depends(get_session), current_user=Depends(require_roles(*_READ))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).get_notification(
        notification_id, include_deleted=include_deleted, viewer_user_id=_viewer_scope(current_user)))


@router.post("/{notification_id}/queue", response_model=NotificationRead, summary="Queue a notification.")
def queue_notification(notification_id: uuid.UUID, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_WRITE))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).queue_notification(notification_id))


@router.post("/{notification_id}/send", response_model=NotificationRead, summary="Send a notification.")
def send_notification(notification_id: uuid.UUID, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_WRITE))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).send_notification(notification_id))


@router.post("/{notification_id}/retry", response_model=NotificationRead, summary="Retry a failed notification.")
def retry_notification(notification_id: uuid.UUID, session: Session = Depends(get_session),
                       current_user=Depends(require_roles(*_WRITE))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).retry_notification(notification_id))


@router.post("/{notification_id}/cancel", response_model=NotificationRead, summary="Cancel a notification.")
def cancel_notification(notification_id: uuid.UUID, payload: NotificationCancelRequest, session: Session = Depends(get_session),
                        current_user=Depends(require_roles(*_WRITE))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).cancel_notification(notification_id, reason=payload.reason))


@router.post("/{notification_id}/read", response_model=NotificationRead, summary="Mark a notification read.")
def read_notification(notification_id: uuid.UUID, session: Session = Depends(get_session),
                      current_user=Depends(require_roles(*_READ))) -> NotificationRead:
    return NotificationRead.model_validate(NotificationService(session).mark_read(
        notification_id, viewer_user_id=_viewer_scope(current_user)))


@router.get("/{notification_id}/attempts", response_model=list[NotificationDeliveryAttemptRead],
            summary="List delivery attempts for a notification.")
def list_attempts(notification_id: uuid.UUID, session: Session = Depends(get_session),
                  current_user=Depends(require_roles(*_READ))) -> list[NotificationDeliveryAttemptRead]:
    return [NotificationDeliveryAttemptRead.model_validate(x) for x in NotificationService(session).list_delivery_attempts(notification_id)]
