"""Append permanent receipt rounds here. Never edit a received round.

Provisional placement: cables C1/L1; charger heads C2/L1; headphones and
unconfirmed Oraimo C1/L2; remaining chargers C2/L2; memory C1/L3; flash C2/L3.
Zero is the schema's unset selling-price default, not a confirmed retail price.
"""

ROUND_1_LINES = (
    ("AMAYA-MICRO", "Amaya Fast Micro cable", 2, 160, "AL1C1S1"),
    (
        "PROVISIONAL-147-02",
        "PROVISIONAL: Charger head, first receipt model awaiting physical confirmation",
        2,
        70,
        "AL1C2S1",
    ),
    (
        "PROVISIONAL-147-03",
        "PROVISIONAL: Swift/Amaya charger head, exact model awaiting physical confirmation",
        2,
        150,
        "AL1C2S1",
    ),
    ("P47", "P47 headphones", 1, 390, "AL2C1S1"),
    ("PROVISIONAL-147-05", "PROVISIONAL: Oraimo item, exact model awaiting physical confirmation", 1, 650, "AL2C1S1"),
    ("ORAIMO-ORIGINAL-CHARGER", "Original Oraimo charger", 2, 300, "AL2C2S1"),
    ("ORAIMO-TYPE-C-COPY", "Oraimo Type-C copy", 1, 160, "AL2C2S1"),
    ("MEMORY-2GB", "2 GB memory card", 1, 300, "AL3C1S1"),
    ("MEMORY-4GB", "4 GB memory card", 1, 320, "AL3C1S1"),
    ("MEMORY-8GB", "8 GB memory card", 1, 340, "AL3C1S1"),
    ("MEMORY-16GB", "16 GB memory card", 1, 450, "AL3C1S1"),
    ("FLASH-4GB", "4 GB flash disk", 1, 240, "AL3C2S1"),
    ("FLASH-8GB", "8 GB flash disk", 1, 380, "AL3C2S1"),
    ("FLASH-16GB", "16 GB flash disk", 1, 600, "AL3C2S1"),
)
ROUNDS = (
    {
        "key": "lintech-opening-lycom-147-round-1-v1",
        "supplier": "Lycom Mobile Accessories",
        "reference": "147",
        "date": "2026-08-25",
        "notes": "Opening stock captured from existing supplier receipt",
        "expected_lines": 14,
        "expected_quantity": 18,
        "expected_cost": "5190",
        "category": "mobile-accessories",
        "lines": ROUND_1_LINES,
    },
)
