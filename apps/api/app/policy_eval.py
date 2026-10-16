"""Retrieval check for the policy search (P5-T1). Questions fixed before the first run.

The questions and the policies are both written by the developer, so this
tests the search mechanics, not real-world quality. Questions 10-12 are
paraphrases that avoid the policies' own words, to measure the known weakness
of keyword search (no synonyms).

Run against a database that has the policies loaded (it loads them first):
    python -m app.policy_eval
"""

import json
import sys

from sqlalchemy.orm import Session

from app.database import get_engine
from app.policies_service import search_policies, sync_policies

# (question, expected citation, paraphrased?)
QUESTIONS = [
    (
        "What service level do replenishment calculations use by default?",
        "policy:replenishment#service-level",
        False,
    ),
    ("minimum order quantity and pack size", "policy:replenishment#order-quantities", False),
    ("When is stock considered excess?", "policy:replenishment#stock-status", False),
    (
        "Can a warehouse give away stock it needs itself?",
        "policy:stock-transfers#which-stock-can-move",
        False,
    ),
    ("Who is allowed to approve a purchase order?", "policy:approvals#who-approves", False),
    (
        "late deliveries supplier on-time rate threshold",
        "policy:supplier-performance#measuring-delivery-performance",
        False,
    ),
    (
        "What happens if a delivery does not fit in the warehouse?",
        "policy:receiving#warehouse-capacity",
        False,
    ),
    (
        "Is Olist data joined with the simulated suppliers?",
        "policy:data-and-ai-use#data-labels",
        False,
    ),
    ("Can the AI copilot place orders?", "policy:data-and-ai-use#ai-copilot-limits", False),
    (
        "How sure do we want to be that shelves stay filled?",
        "policy:replenishment#service-level",
        True,
    ),
    (
        "Which vendors are unreliable?",
        "policy:supplier-performance#measuring-delivery-performance",
        True,
    ),
    ("Who signs off on buying more stock?", "policy:approvals#who-approves", True),
]


def evaluate(session: Session) -> dict:
    rows = []
    for question, expected, paraphrased in QUESTIONS:
        hits = [hit.citation for hit in search_policies(session, question, limit=3)]
        rows.append(
            {
                "question": question,
                "expected": expected,
                "paraphrased": paraphrased,
                "top3": hits,
                "hit_at_1": hits[:1] == [expected],
                "hit_at_3": expected in hits,
            }
        )

    def share(group: list[dict], key: str) -> str:
        return f"{sum(row[key] for row in group)}/{len(group)}"

    direct = [row for row in rows if not row["paraphrased"]]
    paraphrased = [row for row in rows if row["paraphrased"]]
    return {
        "summary": {
            "direct_hit_at_1": share(direct, "hit_at_1"),
            "direct_hit_at_3": share(direct, "hit_at_3"),
            "paraphrased_hit_at_1": share(paraphrased, "hit_at_1"),
            "paraphrased_hit_at_3": share(paraphrased, "hit_at_3"),
        },
        "questions": rows,
    }


def main() -> int:
    with Session(get_engine()) as session:
        sync_policies(session)
        report = evaluate(session)
        session.rollback()  # the check never changes the database
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
