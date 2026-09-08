# Inventory invariants

- Store stock equals the sum of shelf lot balances.
- A transfer changes location by equal opposite amounts and preserves store quantity.
- A stocked sale consumes balances/lots once and creates movements and cost allocations.
- Available equals physical minus active reservations.
- Lot cost is historical and selling price changes never rewrite it.
- Public APIs never expose costs, COGS, profit, lots, allocations or shelf locations.
- Services lock balances and reject insufficient availability.

## Receiving

Product category and physical storage are independent dimensions. A category classifies a product; a shop area, rack, level, and compartment describe where a particular quantity is held. A completed `StockReceipt` is immutable and contains one line per variant and one placement per exact compartment. Each line creates one historical `StockLot`; all placements for that line point to the same lot and create purchase-receipt movements. Receipt completion is atomic and idempotent. A preferred location is created only when the variant has no preferred location.

Racks have explicit category assignments through `ShelfStackCategory`, with one primary category and optional additional allowed categories. Receiving can select only categories assigned to active racks, and every placement is checked against the variant's category on the server. Products remain item families; `ProductVariant` rows represent sellable versions, with flexible option types, values, and assignments. Buying price remains lot-specific; internal views may show latest BP and weighted average stock cost while public APIs expose neither.
