# Replenishment policy

> SIMULATED COMPANY POLICY, written for the ChainPilot demo. It is not the policy of any real company.

Version 1, 2026-10-17. Applies to all simulated (SYN-) products in all simulated (SYN-) warehouses.

## Service level

Stock is planned so that a product does not run out between two deliveries in 95% of replenishment cycles. This is the default service level. A planner may choose a different level, from 50% to just under 100%, for a single recommendation run, for example a higher level for products whose stock-outs lose a lot of margin.

How the system applies this: `POST /inventory/recommendations` and `GET /inventory/risks` use 0.95 unless another `service_level` is given. In the replay test on real demand, the 95% setting kept 94% of item-weeks free of lost sales.

## Weekly review

Stock of every product at every warehouse is reviewed once a week. An order placed at a review must cover the supplier's lead time plus the seven days until the next review. Demand for that period comes from the newest demand forecast, and its uncertainty from the forecast's 80% interval. Variation in the supplier's lead time is added to the safety stock.

## Order quantities

At each review the system recommends enough to bring stock on hand plus stock on order up to the target level (the order-up-to level). Orders follow the supplier's rules: at least the minimum order quantity, and always whole packs. If the shortfall is smaller than the minimum order, the minimum is ordered. An order is never larger than the free space at the receiving warehouse; when space is short, the most urgent items get it first.

## Stock status

Every product at every warehouse has one status:

- Out of stock: nothing on hand while demand is expected.
- At risk: stock on hand plus stock on order is below the reorder point, so the product may run out before a new delivery can arrive.
- Excess: stock on hand is more than 60 days of demand above the target level.
- OK: everything else.

Out-of-stock and at-risk items are handled first.

## When the system cannot plan

The demand forecasts cover 28 days. If a supplier's lead time plus the seven-day review is longer than that, the system does not guess: the item is reported as not assessed and must be planned by hand. Products without a supplier cannot be reordered automatically.
