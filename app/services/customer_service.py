"""Customer service — application layer for the Customer aggregate.

Responsibilities:
  * Enforce all business rules (uniqueness, status-machine, soft-delete).
  * Own the unit of work (single session.commit() per operation).
  * Emit domain events into the transactional outbox in the same transaction.
  * Never import FastAPI or HTTP types — all errors are domain exceptions.

Event emission pattern (ADR-007 / docs/03 §7):
    service.create_customer(...)
    → CustomerRepository.create()     # session.add — no flush yet
    → session.flush()                 # assigns customer.id from DB
    → EventEnvelope.create(event, …)  # wrap payload
    → EventStoreRepository.append()   # flush event row + audit row
    → session.commit()                # atomic: customer + event together
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.customer_events import (
    CustomerActivated,
    CustomerAddressUpdated,
    CustomerContactUpdated,
    CustomerCreated,
    CustomerDeleted,
    CustomerRestored,
    CustomerStatusChanged,
    CustomerSuspended,
    CustomerUpdated,
)
from app.events.envelope import EventEnvelope
from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.repositories.customer_repository import CustomerRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.schemas.customer import CustomerListParams
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    StatusTransitionError,
    ValidationError,
)

_AGGREGATE_TYPE = "Customer"

# Fields treated as contact details (trigger CustomerContactUpdated).
_CONTACT_FIELDS = frozenset(
    {"contact_person", "primary_phone", "secondary_phone", "primary_email", "secondary_email"}
)

# Fields treated as address details (trigger CustomerAddressUpdated).
_ADDRESS_FIELDS = frozenset(
    {"country", "city", "district", "address", "latitude", "longitude"}
)

# Status transitions that are explicitly allowed.
_ALLOWED_TRANSITIONS: Dict[CustomerStatus, frozenset[CustomerStatus]] = {
    CustomerStatus.ACTIVE: frozenset({CustomerStatus.SUSPENDED, CustomerStatus.INACTIVE}),
    CustomerStatus.SUSPENDED: frozenset({CustomerStatus.ACTIVE, CustomerStatus.INACTIVE}),
    CustomerStatus.INACTIVE: frozenset({CustomerStatus.ACTIVE}),
}


class CustomerService:
    """Orchestrates Customer persistence, validation, and event emission."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CustomerRepository(session)
        self._event_repo = EventStoreRepository(session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tenant_id(self) -> uuid.UUID:
        """Return the current tenant from the request context."""
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self) -> Optional[uuid.UUID]:
        """Return the acting user from the request context (nullable for system ops)."""
        return get_current_user_id()

    def _emit(
        self,
        event,
        *,
        aggregate_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        """Wrap a domain event and append it to the transactional outbox."""
        next_version = self._event_repo.next_aggregate_version(aggregate_id)
        envelope = EventEnvelope.create(
            event,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_version=next_version,
            aggregate_type=_AGGREGATE_TYPE,
            user_id=self._actor_id(),
        )
        self._event_repo.append(envelope)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_customer(
        self,
        *,
        code: str,
        company_name: str,
        customer_type,
        status=CustomerStatus.ACTIVE,
        **kwargs,
    ) -> Customer:
        """Create and persist a new customer.

        Args:
            code: Internal tenant-scoped code (uppercased on input).
            company_name: Primary name of the organization.
            customer_type: :class:`~app.models.enums.CustomerType` value.
            status: Initial status (default: active).
            **kwargs: Any other ``Customer`` column values.

        Raises:
            :exc:`ConflictError`: When ``code``, ``commercial_registration``, or
                ``vat_number`` is already used within this tenant.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        # --- business rule: unique code per tenant ---
        if self._repo.get_by_code(code):
            raise ConflictError(f"Customer code '{code}' already exists in this tenant.")

        # --- business rule: unique commercial registration per tenant ---
        cr = kwargs.get("commercial_registration")
        if cr and self._repo.get_by_commercial_registration(cr):
            raise ConflictError(
                f"Commercial registration '{cr}' is already registered in this tenant."
            )

        # --- business rule: unique VAT number per tenant ---
        vat = kwargs.get("vat_number")
        if vat and self._repo.get_by_vat_number(vat):
            raise ConflictError(
                f"VAT number '{vat}' is already registered in this tenant."
            )

        customer = self._repo.create(
            tenant_id=tenant_id,
            code=code.upper(),
            company_name=company_name,
            customer_type=customer_type,
            status=status,
            created_by=actor_id,
            updated_by=actor_id,
            **kwargs,
        )
        self._session.flush()  # → assigns customer.id

        self._emit(
            CustomerCreated(
                customer_id=customer.id,
                tenant_id=tenant_id,
                code=customer.code,
                company_name=customer.company_name,
                customer_type=customer.customer_type.value,
                status=customer.status.value,
            ),
            aggregate_id=customer.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(customer)
        return customer

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_customer(
        self, customer_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Customer:
        """Return a customer by ID, raising :exc:`NotFoundError` if absent.

        Args:
            customer_id: The customer's UUID.
            include_deleted: When ``True``, soft-deleted customers are also returned.

        Raises:
            :exc:`NotFoundError`: When the customer cannot be found.
        """
        customer = self._repo.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found.")
        if customer.is_deleted and not include_deleted:
            raise NotFoundError(f"Customer {customer_id} not found.")
        return customer

    def list_customers(self, params: CustomerListParams) -> Page[Customer]:
        """Return a paginated, filtered, sorted list of customers."""
        items, total = self._repo.list_customers(
            q=params.q,
            status=params.status,
            customer_type=params.customer_type,
            risk_level=params.risk_level,
            credit_status=params.credit_status,
            country=params.country,
            city=params.city,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        # Build a fake PageParams so Page.create() has the right shape.
        pp = PageParams(page=params.page, size=params.size)
        return Page.create(items=items, total=total, params=pp)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_customer(
        self, customer_id: uuid.UUID, **data
    ) -> Customer:
        """Apply partial updates to a customer.

        Validates uniqueness constraints for any updated registration numbers.

        Args:
            customer_id: Target customer ID.
            **data: Fields to change (only non-None values are applied).

        Raises:
            :exc:`NotFoundError`: When the customer is not found.
            :exc:`ConflictError`: On duplicate code / registration / VAT.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        customer = self._repo.get_by_id_or_raise(customer_id)
        if customer.is_deleted:
            raise NotFoundError(f"Customer {customer_id} not found (deleted).")

        # Uniqueness guards for updated unique fields.
        new_cr = data.get("commercial_registration")
        if new_cr and new_cr != customer.commercial_registration:
            existing = self._repo.get_by_commercial_registration(new_cr)
            if existing and existing.id != customer_id:
                raise ConflictError(
                    f"Commercial registration '{new_cr}' already in use."
                )

        new_vat = data.get("vat_number")
        if new_vat and new_vat != customer.vat_number:
            existing = self._repo.get_by_vat_number(new_vat)
            if existing and existing.id != customer_id:
                raise ConflictError(f"VAT number '{new_vat}' already in use.")

        # Track which categories of fields changed for fine-grained events.
        contact_changes = {k: v for k, v in data.items() if k in _CONTACT_FIELDS and v is not None}
        address_changes = {k: v for k, v in data.items() if k in _ADDRESS_FIELDS and v is not None}
        other_changes = {
            k: v
            for k, v in data.items()
            if k not in _CONTACT_FIELDS and k not in _ADDRESS_FIELDS and v is not None
        }

        data["updated_by"] = actor_id
        self._repo.update(customer, **data)
        self._session.flush()

        # Emit specific events when contact / address fields changed.
        if contact_changes:
            self._emit(
                CustomerContactUpdated(
                    customer_id=customer.id,
                    tenant_id=tenant_id,
                    changed_fields=contact_changes,
                ),
                aggregate_id=customer.id,
                tenant_id=tenant_id,
            )
        if address_changes:
            self._emit(
                CustomerAddressUpdated(
                    customer_id=customer.id,
                    tenant_id=tenant_id,
                    changed_fields=address_changes,
                ),
                aggregate_id=customer.id,
                tenant_id=tenant_id,
            )
        if other_changes or (not contact_changes and not address_changes):
            self._emit(
                CustomerUpdated(
                    customer_id=customer.id,
                    tenant_id=tenant_id,
                    changed_fields={**other_changes},
                ),
                aggregate_id=customer.id,
                tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(customer)
        return customer

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def _transition_status(
        self,
        customer_id: uuid.UUID,
        new_status: CustomerStatus,
        *,
        reason: Optional[str] = None,
    ) -> Customer:
        """Common status-change implementation with state-machine validation."""
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        customer = self._repo.get_by_id_or_raise(customer_id)
        if customer.is_deleted:
            raise NotFoundError(f"Customer {customer_id} not found (deleted).")

        previous = customer.status
        if new_status == previous:
            return customer  # idempotent — no-op

        allowed = _ALLOWED_TRANSITIONS.get(previous, frozenset())
        if new_status not in allowed:
            raise StatusTransitionError(
                f"Cannot transition customer from '{previous.value}' to '{new_status.value}'."
            )

        customer.status = new_status
        customer.updated_by = actor_id
        self._session.flush()

        # Emit the specific event for well-known transitions, plus always the
        # general CustomerStatusChanged.
        if new_status == CustomerStatus.ACTIVE:
            self._emit(
                CustomerActivated(
                    customer_id=customer.id,
                    tenant_id=tenant_id,
                    previous_status=previous.value,
                ),
                aggregate_id=customer.id,
                tenant_id=tenant_id,
            )
        elif new_status == CustomerStatus.SUSPENDED:
            self._emit(
                CustomerSuspended(
                    customer_id=customer.id,
                    tenant_id=tenant_id,
                    previous_status=previous.value,
                    reason=reason,
                ),
                aggregate_id=customer.id,
                tenant_id=tenant_id,
            )

        self._emit(
            CustomerStatusChanged(
                customer_id=customer.id,
                tenant_id=tenant_id,
                previous_status=previous.value,
                new_status=new_status.value,
                reason=reason,
            ),
            aggregate_id=customer.id,
            tenant_id=tenant_id,
        )

        self._session.commit()
        self._session.refresh(customer)
        return customer

    def activate_customer(
        self, customer_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Customer:
        """Set status → active."""
        return self._transition_status(
            customer_id, CustomerStatus.ACTIVE, reason=reason
        )

    def suspend_customer(
        self, customer_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Customer:
        """Set status → suspended."""
        return self._transition_status(
            customer_id, CustomerStatus.SUSPENDED, reason=reason
        )

    def deactivate_customer(
        self, customer_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Customer:
        """Set status → inactive."""
        return self._transition_status(
            customer_id, CustomerStatus.INACTIVE, reason=reason
        )

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def delete_customer(self, customer_id: uuid.UUID) -> None:
        """Soft-delete a customer.

        Raises:
            :exc:`NotFoundError`: When the customer is not found or already deleted.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        customer = self._repo.get_by_id_or_raise(customer_id)
        if customer.is_deleted:
            raise NotFoundError(f"Customer {customer_id} is already deleted.")

        self._repo.soft_delete(customer, deleted_by=actor_id)
        customer.updated_by = actor_id
        self._session.flush()

        self._emit(
            CustomerDeleted(
                customer_id=customer.id,
                tenant_id=tenant_id,
                deleted_by=actor_id,
            ),
            aggregate_id=customer.id,
            tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_customer(self, customer_id: uuid.UUID) -> Customer:
        """Restore a soft-deleted customer.

        Raises:
            :exc:`NotFoundError`: When the customer is not found.
            :exc:`ValidationError`: When the customer is not currently deleted.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        # Must explicitly look up including deleted rows.
        customer = self._repo.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found.")
        if not customer.is_deleted:
            raise ValidationError(f"Customer {customer_id} is not deleted; nothing to restore.")

        self._repo.restore(customer)
        customer.updated_by = actor_id
        self._session.flush()

        self._emit(
            CustomerRestored(
                customer_id=customer.id,
                tenant_id=tenant_id,
            ),
            aggregate_id=customer.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(customer)
        return customer
