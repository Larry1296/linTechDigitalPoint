# Architecture

React uses same-origin session cookies and CSRF with versioned DRF endpoints. Django permissions are authoritative. Domain services own inventory writes and row locks. PostgreSQL constraints reject negative or over-reserved balances.

Core owns settings and audit; catalog owns product/service definitions and price history; inventory owns zones, dynamic geometry, lots, balances, movements and reservations; commerce owns sales, payments and frozen cost allocations.

