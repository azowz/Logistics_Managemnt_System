"""Order service — application layer for the Order aggregate.

Responsibilities:
  * Enforce business rules (customer existence, order-number uniqueness,
    lifecycle state machine, soft-delete).
  * Own the unit of work (single ``session.commit()`` per operation).
  * Emit domain events into the transactional outbox in the same transaction.
  * Never import FastAPI/HTTP types — failures are domain exceptions.

Event emission follows the Sprint 3 pattern:
    repo.create/update (no commit) → session.flush() → EventEnvelope.create()
    → EventStoreRepository.append() → session.commit()  (atomic)
"""

from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.order_events import (
    OrderAddressChanged,
    OrderApproved,
    OrderAssigned,
    OrderCancelled,
    OrderCreated,
    OrderDeleted,
    OrderDelivered,
    OrderFailed,
    OrderInTransit,
    OrderPickedUp,
    OrderPriorityChanged,
    OrderRestored,
    OrderScheduled,
    OrderStatusChanged,
    OrderSubmitted,
    OrderUpdated,
)
from app.models.enums import OrderStatus
from app.models.order import Order
from app.repositories.customer_repository import CustomerRepository
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.user_repository import UserRepository
from app.schemas.order import OrderListParams
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.services.order_policies import OrderStateMachine

_AGGREGATE_TYPE = "Order"

# Fields whose change emits OrderAddressChanged.
_ADDRESS_FIELDS = frozenset(
    {
        "pickup_location",
        "delivery_location",
        "pickup_latitude",
        "pickup_longitude",
        "delivery_latitude",
        "delivery_longitude",
    }
)


class OrderService:
    """Orchestrates Order persistence, validation, and event emission."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = OrderRepository(session)
        self._customer_repo = CustomerRepository(session)
        self._user_repo = UserRepository(session)
        self._event_repo = EventStoreRepository(session)

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self) -> Optional[uuid.UUID]:
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
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

    @staticmethod
    def _generate_order_number() -> str:
        """Generate a tenant-unique-ish order number; uniqueness is re-checked."""
        return f"ORD-{uuid.uuid4().hex[:12].upper()}"

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_order(
        self,
        *,
        customer_id: uuid.UUID,
        order_number: Optional[str] = None,
        **kwargs,
    ) -> Order:
        """Create and persist a new order in ``draft`` status.

        Raises:
            :exc:`ValidationError`: When the customer does not exist in the tenant.
            :exc:`ConflictError`: When ``order_number`` already exists in the tenant.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        # --- business rule: customer must exist (and not be soft-deleted) ---
        customer = self._customer_repo.get_by_id(customer_id)
        if customer is None or customer.is_deleted:
            raise ValidationError(
                f"Customer {customer_id} does not exist in this tenant."
            )

        # --- business rule: unique order number per tenant ---
        number = (order_number or self._generate_order_number()).upper()
        if self._repo.get_by_order_number(number):
            raise ConflictError(
                f"Order number '{number}' already exists in this tenant."
            )

        # Status is always DRAFT on creation regardless of input.
        kwargs.pop("status", None)

        order = self._repo.create(
            tenant_id=tenant_id,
            customer_id=customer_id,
            order_number=number,
            status=OrderStatus.DRAFT,
            created_by=actor_id,
            updated_by=actor_id,
            **kwargs,
        )
        self._session.flush()  # → assigns order.id

        self._emit(
            OrderCreated(
                order_id=order.id,
                tenant_id=tenant_id,
                customer_id=order.customer_id,
                order_number=order.order_number,
                order_type=order.order_type.value,
                order_source=order.order_source.value,
                priority=order.priority.value,
                status=order.status.value,
            ),
            aggregate_id=order.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(order)
        return order

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_order(
        self, order_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Order:
        """Return an order by ID, raising :exc:`NotFoundError` if absent/deleted."""
        order = self._repo.get_by_id(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found.")
        if order.is_deleted and not include_deleted:
            raise NotFoundError(f"Order {order_id} not found.")
        return order

    def list_orders(self, params: OrderListParams) -> Page[Order]:
        """Return a paginated, filtered, sorted list of orders."""
        items, total = self._repo.list_orders(
            q=params.q,
            status=params.status,
            order_type=params.order_type,
            order_source=params.order_source,
            priority=params.priority,
            customer_id=params.customer_id,
            assigned_dispatcher_id=params.assigned_dispatcher_id,
            include_deleted=params.include_deleted,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
            limit=params.size,
            offset=params.offset,
        )
        pp = PageParams(page=params.page, size=params.size)
        return Page.create(items=items, total=total, params=pp)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_order(self, order_id: uuid.UUID, **data) -> Order:
        """Apply partial updates to an order (PATCH semantics).

        Emits :class:`OrderPriorityChanged` when priority changes,
        :class:`OrderAddressChanged` when any location field changes, and a
        general :class:`OrderUpdated` for the remaining changes.

        Raises:
            :exc:`NotFoundError`: When the order is missing or deleted.
            :exc:`ValidationError`: When attempting to update a terminal order.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        order = self._repo.get_by_id_or_raise(order_id)
        if order.is_deleted:
            raise NotFoundError(f"Order {order_id} not found (deleted).")
        if OrderStateMachine.is_terminal(order.status):
            raise ValidationError(
                f"Order {order_id} is in terminal state '{order.status.value}' and cannot be edited."
            )

        # Detect priority change BEFORE applying updates.
        new_priority = data.get("priority")
        previous_priority = order.priority
        priority_changed = new_priority is not None and new_priority != previous_priority

        # Partition changed fields for fine-grained events.
        applied = {k: v for k, v in data.items() if v is not None}
        address_changes = {k: v for k, v in applied.items() if k in _ADDRESS_FIELDS}
        other_changes = {
            k: v
            for k, v in applied.items()
            if k not in _ADDRESS_FIELDS and k != "priority"
        }

        data["updated_by"] = actor_id
        self._repo.update(order, **data)
        self._session.flush()

        if priority_changed:
            self._emit(
                OrderPriorityChanged(
                    order_id=order.id,
                    tenant_id=tenant_id,
                    previous_priority=previous_priority.value,
                    new_priority=order.priority.value,
                ),
                aggregate_id=order.id,
                tenant_id=tenant_id,
            )
        if address_changes:
            self._emit(
                OrderAddressChanged(
                    order_id=order.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(address_changes),
                ),
                aggregate_id=order.id,
                tenant_id=tenant_id,
            )
        # Emit a general OrderUpdated only for changes not already covered by the
        # priority/address-specific events. A no-op update emits nothing (the API
        # also rejects empty PATCH bodies via OrderUpdate.at_least_one_field).
        if other_changes:
            self._emit(
                OrderUpdated(
                    order_id=order.id,
                    tenant_id=tenant_id,
                    changed_fields=_jsonable(other_changes),
                ),
                aggregate_id=order.id,
                tenant_id=tenant_id,
            )

        self._session.commit()
        self._session.refresh(order)
        return order

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition(
        self,
        order_id: uuid.UUID,
        new_status: OrderStatus,
        *,
        reason: Optional[str] = None,
        mutate: Optional[Callable[[Order], None]] = None,
        extra_events: Optional[List[Callable[[Order, OrderStatus], object]]] = None,
    ) -> Order:
        """Validated status transition + event emission, in one transaction.

        Args:
            order_id: Target order.
            new_status: Desired status.
            reason: Optional human-readable reason (carried on events).
            mutate: Optional callback to set status-specific fields/timestamps.
            extra_events: Factories ``(order, previous) -> event`` emitted before
                the always-emitted :class:`OrderStatusChanged`.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        order = self._repo.get_by_id_or_raise(order_id)
        if order.is_deleted:
            raise NotFoundError(f"Order {order_id} not found (deleted).")

        previous = order.status
        if new_status == previous:
            return order  # idempotent no-op

        OrderStateMachine.validate_transition(previous, new_status)

        if mutate is not None:
            mutate(order)
        order.status = new_status
        order.updated_by = actor_id
        self._session.flush()

        for factory in extra_events or []:
            self._emit(
                factory(order, previous), aggregate_id=order.id, tenant_id=tenant_id
            )

        self._emit(
            OrderStatusChanged(
                order_id=order.id,
                tenant_id=tenant_id,
                previous_status=previous.value,
                new_status=new_status.value,
                reason=reason,
            ),
            aggregate_id=order.id,
            tenant_id=tenant_id,
        )

        self._session.commit()
        self._session.refresh(order)
        return order

    def submit_order(self, order_id: uuid.UUID) -> Order:
        """draft → submitted."""
        def _mutate(o: Order) -> None:
            o.submitted_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.SUBMITTED,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderSubmitted(
                    order_id=o.id, tenant_id=o.tenant_id, previous_status=prev.value
                )
            ],
        )

    def approve_order(
        self, order_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Order:
        """submitted → approved."""
        def _mutate(o: Order) -> None:
            o.approved_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.APPROVED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderApproved(
                    order_id=o.id,
                    tenant_id=o.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    def schedule_order(self, order_id: uuid.UUID) -> Order:
        """approved → scheduled."""
        def _mutate(o: Order) -> None:
            o.scheduled_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.SCHEDULED,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderScheduled(
                    order_id=o.id, tenant_id=o.tenant_id, previous_status=prev.value
                )
            ],
        )

    def assign_order(
        self,
        order_id: uuid.UUID,
        *,
        assigned_dispatcher_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> Order:
        """scheduled → assigned (sets the dispatcher).

        Validates that the dispatcher exists within the current tenant — RLS
        already filters cross-tenant rows to ``None``, and the explicit
        tenant-id check is defence-in-depth (and meaningful where RLS is absent).

        Raises:
            :exc:`ValidationError`: When the dispatcher is unknown or belongs to
                another tenant.
        """
        tenant_id = self._tenant_id()
        dispatcher = self._user_repo.get_by_id(assigned_dispatcher_id)
        if (
            dispatcher is None
            or getattr(dispatcher, "is_deleted", False)
            or dispatcher.tenant_id != tenant_id
        ):
            raise ValidationError(
                f"Dispatcher {assigned_dispatcher_id} does not exist in this tenant."
            )

        def _mutate(o: Order) -> None:
            o.assigned_dispatcher_id = assigned_dispatcher_id
            o.assigned_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.ASSIGNED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderAssigned(
                    order_id=o.id,
                    tenant_id=o.tenant_id,
                    assigned_dispatcher_id=o.assigned_dispatcher_id,
                    previous_status=prev.value,
                )
            ],
        )

    def start_transit_order(self, order_id: uuid.UUID) -> Order:
        """assigned → in_transit (cargo picked up). Emits OrderPickedUp + OrderInTransit."""
        def _mutate(o: Order) -> None:
            o.picked_up_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.IN_TRANSIT,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderPickedUp(
                    order_id=o.id,
                    tenant_id=o.tenant_id,
                    picked_up_at=o.picked_up_at.isoformat() if o.picked_up_at else None,
                    previous_status=prev.value,
                ),
                lambda o, prev: OrderInTransit(
                    order_id=o.id, tenant_id=o.tenant_id, previous_status=prev.value
                ),
            ],
        )

    def deliver_order(self, order_id: uuid.UUID) -> Order:
        """in_transit → delivered (terminal)."""
        def _mutate(o: Order) -> None:
            o.delivered_at = utcnow()

        return self._transition(
            order_id,
            OrderStatus.DELIVERED,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderDelivered(
                    order_id=o.id,
                    tenant_id=o.tenant_id,
                    delivered_at=o.delivered_at.isoformat() if o.delivered_at else None,
                    previous_status=prev.value,
                )
            ],
        )

    def cancel_order(
        self, order_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Order:
        """any non-terminal → cancelled (terminal). Flags compensation when needed."""
        def _mutate(o: Order) -> None:
            o.cancelled_at = utcnow()
            o.cancellation_reason = reason

        # Compensation requirement depends on the PREVIOUS status, captured here.
        def _cancelled_event(o: Order, prev: OrderStatus) -> object:
            return OrderCancelled(
                order_id=o.id,
                tenant_id=o.tenant_id,
                previous_status=prev.value,
                reason=reason,
                compensation_required=OrderStateMachine.requires_compensation(prev),
            )

        return self._transition(
            order_id,
            OrderStatus.CANCELLED,
            reason=reason,
            mutate=_mutate,
            extra_events=[_cancelled_event],
        )

    def fail_order(
        self, order_id: uuid.UUID, *, reason: Optional[str] = None
    ) -> Order:
        """non-terminal → failed (terminal)."""
        def _mutate(o: Order) -> None:
            o.failed_at = utcnow()
            o.failure_reason = reason

        return self._transition(
            order_id,
            OrderStatus.FAILED,
            reason=reason,
            mutate=_mutate,
            extra_events=[
                lambda o, prev: OrderFailed(
                    order_id=o.id,
                    tenant_id=o.tenant_id,
                    previous_status=prev.value,
                    reason=reason,
                )
            ],
        )

    # ------------------------------------------------------------------
    # Soft-delete / restore
    # ------------------------------------------------------------------

    def delete_order(self, order_id: uuid.UUID) -> None:
        """Soft-delete an order.

        Raises:
            :exc:`NotFoundError`: When the order is missing or already deleted.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        order = self._repo.get_by_id_or_raise(order_id)
        if order.is_deleted:
            raise NotFoundError(f"Order {order_id} is already deleted.")

        self._repo.soft_delete(order, deleted_by=actor_id)
        order.updated_by = actor_id
        self._session.flush()

        self._emit(
            OrderDeleted(
                order_id=order.id, tenant_id=tenant_id, deleted_by=actor_id
            ),
            aggregate_id=order.id,
            tenant_id=tenant_id,
        )
        self._session.commit()

    def restore_order(self, order_id: uuid.UUID) -> Order:
        """Restore a soft-deleted order.

        Raises:
            :exc:`NotFoundError`: When the order does not exist.
            :exc:`ValidationError`: When the order is not currently deleted.
        """
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()

        order = self._repo.get_by_id(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found.")
        if not order.is_deleted:
            raise ValidationError(
                f"Order {order_id} is not deleted; nothing to restore."
            )

        self._repo.restore(order)
        order.updated_by = actor_id
        self._session.flush()

        self._emit(
            OrderRestored(order_id=order.id, tenant_id=tenant_id),
            aggregate_id=order.id,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(order)
        return order


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    """Coerce update values into JSON-safe primitives for event payloads."""
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
