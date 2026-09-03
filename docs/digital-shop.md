# Digital Shop physical hierarchy

Digital Shop is a digital twin of the shelving that physically exists at LinTech Digital Point. It never creates sample racks automatically.

```text
Store → Zone → ShelfStack → ShelfLevel → Shelf → StockBalance → StockLot/ProductVariant
```

The Owner chooses a zone, records the stack's real position and dimensions in the Store measurement unit (normally centimetres), defines each level's compartment count, previews the full rack, and creates it transactionally. Codes such as `RIGHT-R01-L03-S02` are permanent; friendly names and physical sticker labels remain editable.

Existing pre-stack shelves remain valid with `level = null` and appear as unassigned physical shelves. Their balances are never deleted.

`VariantPreferredLocation` records where an item normally belongs. It does not represent quantity. `StockBalance` remains authoritative and can place the same variant on several shelves.

Creating a stock item can optionally create opening stock in one exact shelf. Product, variant, preference, opening lot, balance, `OPENING_STOCK` movement, and audit entry are written in one transaction. A zero-quantity item stores only its preferred shelf. Service products require no shelf.

Receiving supports multiple exact placements. POS and online pick lists expose the full hierarchy only to internal staff. Stack archival is blocked while any contained shelf has stock.

Key endpoints:

- `GET /api/v1/locations/zones/`
- `GET|POST /api/v1/locations/stacks/`
- `GET|PATCH|DELETE /api/v1/locations/stacks/{id}/`
- `GET /api/v1/locations/levels/`
- `GET|PATCH /api/v1/locations/shelves/{id}/`
- `GET /api/v1/locations/shelves/{id}/contents/`
- `POST /api/v1/catalog/products/create-with-stock/`
