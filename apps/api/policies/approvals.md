# Approval policy

> SIMULATED COMPANY POLICY, written for the ChainPilot demo. It is not the policy of any real company.

Version 2, 2026-10-17 (version 1 said approving was not built yet).

## Who approves

Three roles exist. Analysts can read all data. Managers can also approve recommendations, record stock movements and receive purchase orders. Administrators can do everything managers can and also manage users, products and warehouses. A purchase order or transfer may only be approved by a manager or an administrator.

## What needs approval

Every change that affects stock or money is made or approved by a person: purchase orders and stock transfers need a manager's approval, and only managers may record stock movements such as adjustments. Recommendations from the system or from the AI copilot are proposals and change nothing until a manager approves them.

How the system applies this: recommendations are stored as pending proposals. A manager or administrator approves or rejects each one; a rejection needs a reason. Approving carries it out at once, as a simulation: a reorder becomes an open purchase order to the recommended supplier, and a transfer moves the stock between the two warehouses. If an approved transfer cannot be carried out (the sending warehouse no longer has the stock, or the receiving one has no room), the decision is kept as failed with the reason and no stock changes. A recommendation can be decided only once, and only while it is pending; a newer set of recommendations replaces the pending ones.

## Audit trail

Every approval, stock movement, receipt and data import is recorded with who did it and when. Audit records are never edited or deleted.
