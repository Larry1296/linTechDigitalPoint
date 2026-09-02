# Inventory invariants

- Store stock equals the sum of shelf lot balances.
- A transfer changes location by equal opposite amounts and preserves store quantity.
- A stocked sale consumes balances/lots once and creates movements and cost allocations.
- Available equals physical minus active reservations.
- Lot cost is historical and selling price changes never rewrite it.
- Public APIs never expose costs, COGS, profit, lots, allocations or shelf locations.
- Services lock balances and reject insufficient availability.

