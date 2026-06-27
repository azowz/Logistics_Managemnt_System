"""User management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import security
from app.core.security import require_roles
from app.db.session import get_session
from app.models.enums import UserRole
from app.repositories.errors import NotFoundError
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user.",
)
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN)),
) -> UserRead:
    """Create a user; only admins can perform this."""
    repo = UserRepository(session)
    hashed_password = security.hash_password(payload.password)
    user = repo.create(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hashed_password,
        role=payload.role,
        is_active=True,
    )
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get a user by ID.",
)
def get_user(
    user_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
) -> UserRead:
    """Retrieve a user by ID."""
    repo = UserRepository(session)
    user = repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserRead.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Update a user.",
)
def update_user(
    user_id: str,
    payload: UserUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN)),
) -> UserRead:
    """Update user fields; password will be re-hashed if provided."""
    repo = UserRepository(session)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        data["hashed_password"] = security.hash_password(data.pop("password"))
    try:
        user = repo.update(user_id, **data)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a user.",
)
def delete_user(
    user_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    """Delete a user by ID."""
    repo = UserRepository(session)
    try:
        repo.delete(user_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
