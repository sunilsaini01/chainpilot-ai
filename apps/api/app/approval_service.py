"""Approval workflow: a manager's decision on a recommendation, and carrying it out.

Rules (policies/approvals.md): recommendations are proposals; only a manager or
an administrator decides. Approving carries the recommendation out at once, with
simulated actions only:
- a reorder becomes an open purchase order to the recommended supplier;
- a transfer moves the stock through the ledger: out of the source warehouse,
  into the destination (no travel time, as the transfer policy says).

If an approved transfer cannot be carried out now (the source no longer has the
stock, or the destination has no room), the decision is still stored with the
outcome "failed" and the reason, and no stock changes. Rejecting needs a reason.

Safety:
- The recommendation row is locked (FOR UPDATE) before its status is checked, so
  two managers deciding at the same moment cannot both act: the second waits,
  then sees that it is no longer pending.
- Every decision carries the client's Idempotency-Key. A retried request (same
  key, same user, same decision) returns the stored decision instead of acting
  twice; the key used for anything else is refused.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import record_event
from app.inventory_service import InsufficientStockError, WarehouseCapacityError, record_movement
from app.models import (
    Approval,
    ApprovalDecision,
    ApprovalOutcome,
    MovementReason,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Recommendation,
    RecommendationKind,
    RecommendationStatus,
    Supplier,
    User,
)


class RecommendationNotFoundError(Exception):
    pass


class AlreadyDecidedError(Exception):
    """The recommendation is no longer pending (decided, or replaced by a newer run)."""


class IdempotencyKeyReusedError(Exception):
    """The Idempotency-Key was already used for a different decision."""


class ReasonRequiredError(ValueError):
    """Rejecting without a reason."""


@dataclass(frozen=True)
class DecisionResult:
    approval: Approval
    created: bool  # False when a retried request returned the stored decision


def find_approval(session: Session, **where: object) -> Approval | None:
    """One approval with its decider loaded (for the decider's email)."""
    return session.execute(
        select(Approval).options(selectinload(Approval.decided_by)).filter_by(**where)
    ).scalar_one_or_none()


def decide(
    session: Session,
    recommendation_id: int,
    decision: ApprovalDecision,
    comment: str | None,
    actor: User,
    idempotency_key: str,
    today: date,
) -> DecisionResult:
    """Record a decision and, if approved, carry the recommendation out. Does not commit."""
    recommendation = session.execute(
        select(Recommendation).where(Recommendation.id == recommendation_id).with_for_update()
    ).scalar_one_or_none()
    if recommendation is None:
        raise RecommendationNotFoundError(f"Recommendation {recommendation_id} not found")

    # Checked after the lock: a first request with this key has committed by now.
    earlier = find_approval(session, idempotency_key=idempotency_key)
    if earlier is not None:
        same_request = (
            earlier.recommendation_id == recommendation_id
            and earlier.decision == decision
            and earlier.decided_by_user_id == actor.id
        )
        if not same_request:
            raise IdempotencyKeyReusedError(
                "This Idempotency-Key was already used for a different decision"
            )
        return DecisionResult(earlier, created=False)

    if recommendation.status != RecommendationStatus.PENDING:
        raise AlreadyDecidedError(
            f"Recommendation {recommendation_id} is {recommendation.status}, not pending"
        )
    if decision == ApprovalDecision.REJECTED and not comment:
        raise ReasonRequiredError("Give a reason to reject a recommendation")

    approval = Approval(
        recommendation_id=recommendation.id,
        decision=decision,
        comment=comment or None,
        decided_by_user_id=actor.id,
        decided_by=actor,
        idempotency_key=idempotency_key,
    )
    if decision == ApprovalDecision.REJECTED:
        recommendation.status = RecommendationStatus.REJECTED
    else:
        outcome, details, order = carry_out(session, recommendation, actor, today)
        approval.outcome = outcome
        approval.outcome_details = details
        approval.purchase_order_id = order.id if order else None
        recommendation.status = (
            RecommendationStatus.EXECUTED
            if outcome == ApprovalOutcome.EXECUTED
            else RecommendationStatus.FAILED
        )
    session.add(approval)
    session.flush()

    record_event(
        session,
        f"recommendation.{decision}",
        "recommendation",
        recommendation.id,
        actor=actor,
        details={
            "kind": recommendation.kind,
            "quantity": recommendation.quantity,
            "outcome": approval.outcome,
            "comment": comment,
            **approval.outcome_details,
        },
    )
    return DecisionResult(approval, created=True)


def carry_out(
    session: Session, recommendation: Recommendation, actor: User, today: date
) -> tuple[ApprovalOutcome, dict, PurchaseOrder | None]:
    """Execute an approved recommendation. Returns (outcome, details, order created)."""
    if recommendation.kind == RecommendationKind.REORDER:
        order = place_order(session, recommendation, actor, today)
        details = {
            "po_number": order.po_number,
            "expected_date": order.expected_date.isoformat(),
        }
        return ApprovalOutcome.EXECUTED, details, order

    reference = f"REC-{recommendation.id}"
    try:
        # Savepoint: if the second leg fails, the first is undone too, and the
        # failed outcome can still be stored in the same transaction.
        # Locks: source stock row, then destination warehouse and stock rows. Two
        # opposite transfers of one product could wait for each other, but cannot
        # both be pending: a short site never gives stock away (replenishment rules).
        with session.begin_nested():
            sent = record_movement(
                session,
                recommendation.product_id,
                recommendation.source_warehouse_id,
                -recommendation.quantity,
                MovementReason.TRANSFER_OUT,
                reference=reference,
                actor_user_id=actor.id,
            )
            received = record_movement(
                session,
                recommendation.product_id,
                recommendation.warehouse_id,
                recommendation.quantity,
                MovementReason.TRANSFER_IN,
                reference=reference,
                actor_user_id=actor.id,
            )
    except (InsufficientStockError, WarehouseCapacityError) as error:
        return ApprovalOutcome.FAILED, {"error": str(error)}, None
    details = {
        "reference": reference,
        "source_balance_after": sent.balance_after,
        "destination_balance_after": received.balance_after,
    }
    return ApprovalOutcome.EXECUTED, details, None


def place_order(
    session: Session, recommendation: Recommendation, actor: User, today: date
) -> PurchaseOrder:
    """An open purchase order for an approved reorder, at the product's unit cost."""
    supplier = session.get(Supplier, recommendation.supplier_id)
    product = session.get(Product, recommendation.product_id)
    order = PurchaseOrder(
        po_number=f"PO-REC-{recommendation.id:06d}",
        supplier_id=supplier.id,
        warehouse_id=recommendation.warehouse_id,
        status=PurchaseOrderStatus.OPEN,
        ordered_date=today,
        expected_date=today + timedelta(days=supplier.lead_time_days),
        lines=[
            PurchaseOrderLine(
                product_id=product.id,
                quantity=recommendation.quantity,
                unit_cost=product.unit_cost,
            )
        ],
    )
    session.add(order)
    session.flush()
    record_event(
        session,
        "purchase_order.created",
        "purchase_order",
        order.id,
        actor=actor,
        details={
            "po_number": order.po_number,
            "recommendation_id": recommendation.id,
            "warehouse_id": order.warehouse_id,
            "units": recommendation.quantity,
        },
    )
    return order
