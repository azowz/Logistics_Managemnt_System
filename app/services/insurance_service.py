"""Insurance service — policies & coverage rules (context #17, Sprint 8).

Owns the unit of work and outbox emission for `InsurancePolicy` and
`CoverageRule`. No FastAPI; failures are domain exceptions.
"""

from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.common.datetime import utcnow
from app.common.pagination import Page, PageParams
from app.db.tenant import get_current_tenant, get_current_user_id
from app.events.envelope import EventEnvelope
from app.events.insurance_events import (
    CoverageRuleCreated,
    CoverageRuleUpdated,
    InsurancePolicyActivated,
    InsurancePolicyCancelled,
    InsurancePolicyCreated,
    InsurancePolicyExpired,
    InsurancePolicySuspended,
)
from app.models.enums import InsurancePolicyStatus
from app.models.insurance import CoverageRule, InsurancePolicy
from app.repositories.event_store_repository import EventStoreRepository
from app.repositories.insurance_repository import (
    CoverageRuleRepository,
    InsurancePolicyRepository,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.insurance_policies import PolicyStateMachine


class InsuranceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._policies = InsurancePolicyRepository(session)
        self._rules = CoverageRuleRepository(session)
        self._event_repo = EventStoreRepository(session)

    def _tenant_id(self) -> uuid.UUID:
        tid = get_current_tenant()
        if tid is None:
            raise ValidationError("No tenant context found; request is not authenticated.")
        return tid

    def _actor_id(self):
        return get_current_user_id()

    def _emit(self, event, *, aggregate_id, aggregate_type, tenant_id):
        nv = self._event_repo.next_aggregate_version(aggregate_id)
        env = EventEnvelope.create(event, tenant_id=tenant_id, aggregate_id=aggregate_id,
                                   aggregate_version=nv, aggregate_type=aggregate_type, user_id=self._actor_id())
        self._event_repo.append(env)

    @staticmethod
    def _generate_policy_number() -> str:
        return f"POL-{uuid.uuid4().hex[:12].upper()}"

    # --- policies ---

    def create_policy(self, *, policy_number: Optional[str] = None, **data) -> InsurancePolicy:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        number = policy_number or self._generate_policy_number()
        if self._policies.get_by_number(number):
            raise ConflictError(f"Policy number '{number}' already exists in this tenant.")
        data.pop("status", None)
        policy = self._policies.create(
            tenant_id=tenant_id, policy_number=number, status=InsurancePolicyStatus.DRAFT,
            created_by=actor_id, updated_by=actor_id, **data,
        )
        self._session.flush()
        self._emit(
            InsurancePolicyCreated(policy_id=policy.id, tenant_id=tenant_id, policy_number=number,
                                   policy_type=policy.policy_type.value, status=policy.status.value),
            aggregate_id=policy.id, aggregate_type="InsurancePolicy", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def _policy_transition(self, policy_id, new_status, *, mutate=None, extra_events=None) -> InsurancePolicy:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        policy = self._policies.get_by_id_or_raise(policy_id)
        if policy.is_deleted:
            raise NotFoundError(f"Policy {policy_id} not found (deleted).")
        previous = policy.status
        if new_status == previous:
            return policy
        PolicyStateMachine.validate_transition(previous, new_status)
        if mutate is not None:
            mutate(policy)
        policy.status = new_status
        policy.updated_by = actor_id
        self._session.flush()
        for factory in extra_events or []:
            self._emit(factory(policy, previous), aggregate_id=policy.id,
                       aggregate_type="InsurancePolicy", tenant_id=tenant_id)
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def activate_policy(self, policy_id):
        return self._policy_transition(
            policy_id, InsurancePolicyStatus.ACTIVE,
            extra_events=[lambda p, prev: InsurancePolicyActivated(policy_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def suspend_policy(self, policy_id, *, reason=None):
        return self._policy_transition(
            policy_id, InsurancePolicyStatus.SUSPENDED,
            extra_events=[lambda p, prev: InsurancePolicySuspended(policy_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def expire_policy(self, policy_id):
        return self._policy_transition(
            policy_id, InsurancePolicyStatus.EXPIRED,
            extra_events=[lambda p, prev: InsurancePolicyExpired(policy_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value)],
        )

    def cancel_policy(self, policy_id, *, reason=None):
        return self._policy_transition(
            policy_id, InsurancePolicyStatus.CANCELLED,
            extra_events=[lambda p, prev: InsurancePolicyCancelled(policy_id=p.id, tenant_id=p.tenant_id, previous_status=prev.value, reason=reason)],
        )

    def get_policy(self, policy_id, *, include_deleted=False) -> InsurancePolicy:
        policy = self._policies.get_by_id(policy_id)
        if policy is None or (policy.is_deleted and not include_deleted):
            raise NotFoundError(f"Policy {policy_id} not found.")
        return policy

    def update_policy(self, policy_id, **data) -> InsurancePolicy:
        self._tenant_id()
        actor_id = self._actor_id()
        policy = self._policies.get_by_id_or_raise(policy_id)
        if policy.is_deleted:
            raise NotFoundError(f"Policy {policy_id} not found (deleted).")
        if PolicyStateMachine.is_terminal(policy.status):
            raise ValidationError(f"Policy {policy_id} is terminal and cannot be edited.")
        data["updated_by"] = actor_id
        self._policies.update(policy, **data)
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def list_policies(self, params) -> Page[InsurancePolicy]:
        items, total = self._policies.list_policies(
            q=params.q, status=params.status, policy_type=params.policy_type,
            include_deleted=params.include_deleted, sort_by=params.sort_by,
            sort_dir=params.sort_dir, limit=params.size, offset=params.offset,
        )
        return Page.create(items=items, total=total, params=PageParams(page=params.page, size=params.size))

    # --- coverage rules ---

    def create_coverage_rule(self, **data) -> CoverageRule:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        policy = self._policies.get_by_id(data["policy_id"])
        if policy is None or policy.is_deleted or policy.tenant_id != tenant_id:
            raise ValidationError(f"Policy {data['policy_id']} does not exist in this tenant.")
        rule = self._rules.create(tenant_id=tenant_id, created_by=actor_id, updated_by=actor_id, **data)
        self._session.flush()
        self._emit(
            CoverageRuleCreated(rule_id=rule.id, tenant_id=tenant_id, policy_id=rule.policy_id,
                                coverage_type=rule.coverage_type.value),
            aggregate_id=rule.id, aggregate_type="CoverageRule", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(rule)
        return rule

    def update_coverage_rule(self, rule_id, **data) -> CoverageRule:
        tenant_id = self._tenant_id()
        actor_id = self._actor_id()
        rule = self._rules.get_by_id_or_raise(rule_id)
        if rule.is_deleted:
            raise NotFoundError(f"Coverage rule {rule_id} not found (deleted).")
        applied = {k: v for k, v in data.items() if v is not None}
        data["updated_by"] = actor_id
        self._rules.update(rule, **data)
        self._session.flush()
        self._emit(
            CoverageRuleUpdated(rule_id=rule.id, tenant_id=tenant_id, changed_fields=_jsonable(applied)),
            aggregate_id=rule.id, aggregate_type="CoverageRule", tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(rule)
        return rule

    def list_coverage_rules(self, *, policy_id=None, limit=50, offset=0):
        return self._rules.list_rules(policy_id=policy_id, limit=limit, offset=offset)


def _jsonable(data: Dict[str, object]) -> Dict[str, object]:
    from app.events.domain_event import to_jsonable

    return {k: to_jsonable(v) for k, v in data.items()}
