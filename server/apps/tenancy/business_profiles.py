"""What kinds of business the platform serves, and how each one is set up.

This catalogue is the single source of truth for registration and settings. The owner first says
how the business makes money (its *model*): selling goods, providing services, or both. The model
decides which tools can exist at all, so a barbershop is never asked about shelves or stock
counts. The owner then picks a *sector* (barbershop, mama mboga, phone repair…), which chooses the
usual tools and offers a starter price list or product categories.

The platform currently targets small and medium businesses. Large companies and supermarkets
(multi-warehouse, purchasing departments, loyalty programmes) are a later phase and are not
offered here.
"""

GOODS, SERVICES, MIXED = "GOODS", "SERVICES", "MIXED"

MODULES = {
    "inventory": {"label": "Products & stock", "description": "Products, prices, receiving stock and stock counts."},
    "locations": {"label": "Shelves & locations", "description": "Map your racks and shelves so anyone finds an item fast."},
    "services": {"label": "Services & jobs", "description": "Your service price list, plus job cards for work handed in, such as repairs."},
    "pos": {"label": "Point of sale", "description": "Record each sale at the counter and send receipts by WhatsApp or email."},
    "customers": {"label": "Customers", "description": "Customer records, credit sales and balances owed."},
    "expenses": {"label": "Expenses", "description": "Record money spent, such as rent, transport and electricity."},
    "mpesa": {"label": "M-Pesa agency", "description": "Agent float, deposits, withdrawals and commission."},
    "reports": {"label": "Reports", "description": "Profit and loss, balance sheet and trends."},
    "branches": {"label": "Branches", "description": "Run more than one shop or location."},
    "staff": {"label": "Staff", "description": "Give each person their own sign-in and role."},
}

# A tool that only works alongside another. Each entry lists alternatives: any one of them will do.
MODULE_NEEDS = {
    "pos": ("inventory", "services"),  # a sale needs something to sell: products or services
    "locations": ("inventory",),       # shelves hold stock
}

BUSINESS_MODELS = {
    GOODS: {
        "label": "I sell goods",
        "phrase": "only sell goods",
        "hint": "You buy, grow or make products and sell them: a duka, kibanda, hardware or farm produce.",
        "modules": ["inventory", "locations", "pos", "customers", "expenses", "mpesa", "reports", "branches", "staff"],
        "requires": ["inventory"],
    },
    SERVICES: {
        "label": "I provide services",
        "phrase": "only provide services",
        "hint": "Customers pay for your skill or time: a barber, salon, phone repair fundi or tailor.",
        "modules": ["services", "pos", "customers", "expenses", "mpesa", "reports", "branches", "staff"],
        "requires": ["services", "mpesa"],  # at least one: an M-Pesa agent sells no priced services
    },
    MIXED: {
        "label": "Both goods and services",
        "phrase": "sell goods and provide services",
        "hint": "You sell products and also offer services, such as a cyber that sells phone accessories.",
        "modules": list(MODULES),
        "requires": ["inventory", "services"],  # at least one; the setup suggestions turn on both
    },
}

# Businesses of each size usually need these on top of the sector's tools.
SIZES = {
    "SOLO": {"label": "Just me", "hint": "I run it myself", "modules": []},
    "SMALL": {"label": "2 – 10 people", "hint": "A few workers or helpers", "modules": ["staff"]},
    "MEDIUM": {"label": "11 – 50 people", "hint": "Several staff, maybe more than one location", "modules": ["staff", "branches", "reports"]},
}

BASE = ["pos", "expenses", "reports"]


def _service(name, unit="FIXED", job=False):
    return {"name": name, "billing_unit": unit, "requires_job": job}


def _sector(id, label, hint, modules, categories=(), services=(), keywords=""):
    return {"id": id, "label": label, "hint": hint, "modules": modules,
            "categories": list(categories), "services": list(services), "keywords": keywords}


SECTORS = {
    GOODS: [
        _sector("mama_mboga", "Mama mboga / kibanda", "Fresh vegetables, fruits and cereals", ["inventory", *BASE],
                ["Vegetables", "Fruits", "Cereals & grains", "Eggs", "Cooking essentials"], keywords="grocery greengrocer market stall sokoni"),
        _sector("duka", "Duka / general shop", "Everyday household goods over the counter", ["inventory", "customers", *BASE],
                ["Foodstuffs", "Drinks", "Toiletries", "Household", "Snacks"], keywords="kiosk retail provision shop minimart"),
        _sector("electronics", "Electronics & phone accessories", "Phones, chargers, covers, computers", ["inventory", "locations", "customers", *BASE],
                ["Phones", "Chargers & cables", "Covers & protectors", "Audio", "Computer accessories"], keywords="phone accessories gadgets"),
        _sector("hardware", "Hardware & building supplies", "Tools, cement, electrical, plumbing", ["inventory", "locations", "customers", *BASE],
                ["Building materials", "Tools", "Electrical", "Plumbing", "Paint"], keywords="construction mjengo"),
        _sector("agrovet", "Agrovet & farm inputs", "Seeds, fertiliser, animal feeds and vet medicines", ["inventory", "locations", "customers", *BASE],
                ["Seeds", "Fertilisers", "Animal feeds", "Vet medicines", "Pesticides"], keywords="agro farm inputs"),
        _sector("pharmacy", "Pharmacy / chemist", "Medicines and personal care", ["inventory", "locations", "customers", *BASE],
                ["Medicines", "First aid", "Personal care", "Baby care"], keywords="chemist drugstore"),
        _sector("farm", "Farmer / farm produce", "Sell your harvest, milk, eggs or livestock", ["inventory", "customers", *BASE],
                ["Crops", "Dairy", "Poultry & eggs", "Livestock"], keywords="shamba agriculture dairy poultry kuku"),
        _sector("butchery", "Butchery", "Meat, chicken and fish", ["inventory", "customers", *BASE],
                ["Beef", "Goat", "Chicken", "Fish"], keywords="meat nyama choma"),
        _sector("clothing", "Clothes, shoes & mitumba", "New or second-hand clothing and shoes", ["inventory", "locations", *BASE],
                ["Men", "Women", "Children", "Shoes", "Accessories"], keywords="boutique fashion mitumba"),
        _sector("beauty_shop", "Cosmetics & beauty shop", "Hair, skin care and make-up products", ["inventory", "locations", *BASE],
                ["Hair products", "Skin care", "Make-up", "Fragrance"], keywords="cosmetics"),
        _sector("stationery", "Bookshop & stationery", "Books, stationery and school supplies", ["inventory", "locations", *BASE],
                ["Books", "Stationery", "School supplies"], keywords="books school"),
        _sector("food", "Food kiosk, café or hotel", "Meals, snacks and drinks", ["inventory", *BASE],
                ["Meals", "Snacks", "Drinks"], keywords="restaurant kibanda hotel cafe chips"),
        _sector("drinks", "Drinks & wines shop", "Soft drinks, beer, wines and spirits", ["inventory", "locations", *BASE],
                ["Soft drinks", "Beer", "Wines", "Spirits"], keywords="liquor bar"),
        _sector("gas_water", "Gas & water refill", "Cooking gas refills, cylinders and water", ["inventory", "customers", *BASE],
                ["Gas refills", "Cylinders", "Water refills", "Accessories"], keywords="lpg"),
        _sector("wholesale", "Wholesale / distributor", "Sell in bulk to other businesses", ["inventory", "locations", "customers", *BASE],
                keywords="distributor bulk supplier"),
        _sector("other_goods", "Other goods", "Describe what you sell", ["inventory", *BASE]),
    ],
    SERVICES: [
        _sector("barber", "Barbershop", "Haircuts, shaves and beard trims", ["services", *BASE],
                services=[_service("Haircut"), _service("Kids haircut"), _service("Shave"), _service("Beard trim"), _service("Hair dye")],
                keywords="kinyozi barber"),
        _sector("salon", "Beauty salon", "Hair, nails and make-up", ["services", "customers", *BASE],
                services=[_service("Braiding"), _service("Wash & set"), _service("Relaxer"), _service("Manicure"), _service("Pedicure"), _service("Make-up")],
                keywords="hair nails spa"),
        _sector("phone_repair", "Phone & computer repair", "Screens, batteries, charging ports and software", ["services", "customers", *BASE],
                services=[_service("Screen replacement", job=True), _service("Battery replacement", job=True), _service("Charging port repair", job=True),
                          _service("Software flashing", job=True), _service("Water damage repair", job=True)],
                keywords="fundi simu phone repair laptop"),
        _sector("appliance_repair", "Electrical & appliance repair", "TVs, fridges, radios, irons and wiring", ["services", "customers", *BASE],
                services=[_service("TV repair", job=True), _service("Fridge repair", job=True), _service("Radio & sound system repair", job=True),
                          _service("Iron & kettle repair", job=True), _service("House wiring", "PER_HOUR")],
                keywords="fundi electrician electronics"),
        _sector("tailoring", "Tailoring & fashion design", "Alterations and made-to-measure clothes", ["services", "customers", *BASE],
                services=[_service("Alterations", job=True), _service("Dress making", job=True), _service("Suit making", job=True), _service("School uniform", job=True)],
                keywords="tailor fundi nguo seamstress"),
        _sector("cobbler", "Shoe repair", "Sole repair, stitching and polishing", ["services", *BASE],
                services=[_service("Sole repair", job=True), _service("Stitching", job=True), _service("Shoe polish")],
                keywords="cobbler shoes"),
        _sector("mechanic", "Garage / mechanic", "Car and motorbike service and repair", ["services", "customers", *BASE],
                services=[_service("Vehicle service", job=True), _service("Puncture repair"), _service("Welding", "PER_HOUR"), _service("Boda boda service", job=True)],
                keywords="garage boda motorbike car"),
        _sector("car_wash", "Car wash", "Vehicle and motorbike washing", ["services", *BASE],
                services=[_service("Exterior wash"), _service("Full wash"), _service("Engine wash"), _service("Motorbike wash")],
                keywords="carwash"),
        _sector("laundry", "Laundry & dry cleaning", "Washing, ironing and dry cleaning", ["services", "customers", *BASE],
                services=[_service("Wash & fold", "PER_ITEM", job=True), _service("Dry cleaning", "PER_ITEM", job=True), _service("Ironing", "PER_ITEM")],
                keywords="dhobi laundry"),
        _sector("cyber", "Cyber café & printing", "Printing, photocopy, typing and online services", ["services", *BASE],
                services=[_service("Printing", "PER_PAGE"), _service("Photocopy", "PER_COPY"), _service("Scanning", "PER_PAGE"),
                          _service("Typing", "PER_PAGE"), _service("Browsing", "PER_HOUR"), _service("Online application", "PER_DOCUMENT")],
                keywords="cyber printing photocopy ecitizen kra"),
        _sector("photography", "Photography & video", "Passport photos, events and printing", ["services", "customers", *BASE],
                services=[_service("Passport photos"), _service("Event coverage", job=True), _service("Photo printing", "PER_ITEM")],
                keywords="photo studio"),
        _sector("cleaning", "Cleaning & fumigation", "Homes, offices and pest control", ["services", "customers", *BASE],
                services=[_service("House cleaning"), _service("Office cleaning"), _service("Fumigation"), _service("Carpet cleaning", "PER_ITEM")],
                keywords="cleaners"),
        _sector("mpesa_agent", "M-Pesa / mobile money agent", "Deposits, withdrawals and float", ["mpesa", "expenses", "reports"],
                keywords="agent mobile money float"),
        _sector("other_services", "Other services", "Describe the service you offer", ["services", *BASE]),
    ],
    MIXED: [
        _sector("cyber_shop", "Cyber, accessories & M-Pesa", "Printing and online services, phone accessories and an M-Pesa till",
                ["inventory", "locations", "services", "customers", "mpesa", *BASE],
                ["Phone accessories", "Computer accessories", "Stationery"],
                [_service("Printing", "PER_PAGE"), _service("Photocopy", "PER_COPY"), _service("Typing", "PER_PAGE"), _service("Online application", "PER_DOCUMENT")],
                keywords="cyber digital point"),
        _sector("repair_shop", "Repair shop with spare parts", "Repairs plus spare parts and accessories for sale",
                ["inventory", "services", "customers", *BASE], ["Spare parts", "Accessories"],
                [_service("Screen replacement", job=True), _service("Battery replacement", job=True), _service("Charging port repair", job=True)],
                keywords="fundi phone electronics spares"),
        _sector("salon_shop", "Salon with beauty products", "Hair and beauty services plus products for sale",
                ["inventory", "services", "customers", *BASE], ["Hair products", "Skin care"],
                [_service("Braiding"), _service("Wash & set"), _service("Manicure")], keywords="salon cosmetics"),
        _sector("garage_spares", "Garage with spare parts", "Vehicle repairs plus spare parts and oils",
                ["inventory", "services", "customers", *BASE], ["Spare parts", "Oils & lubricants", "Tyres"],
                [_service("Vehicle service", job=True), _service("Puncture repair")], keywords="mechanic boda"),
        _sector("agrovet_vet", "Agrovet with vet services", "Farm inputs plus animal treatment and AI services",
                ["inventory", "services", "customers", *BASE], ["Animal feeds", "Vet medicines", "Seeds", "Fertilisers"],
                [_service("Animal treatment"), _service("Artificial insemination"), _service("Vaccination")], keywords="vet agro"),
        _sector("tailor_shop", "Tailor with fabrics & clothes", "Tailoring plus fabric and ready-made clothes",
                ["inventory", "services", "customers", *BASE], ["Fabrics", "Ready-made clothes"],
                [_service("Alterations", job=True), _service("Dress making", job=True)], keywords="tailor boutique"),
        _sector("other_mixed", "Other mix of goods and services", "Describe what you sell and do", ["inventory", "services", *BASE]),
    ],
}

SECTOR_INDEX = {sector["id"]: (model, sector) for model, sectors in SECTORS.items() for sector in sectors}
OTHER_SECTORS = {"other_goods", "other_services", "other_mixed"}


def model_for_modules(modules):
    """The business model that fits an existing set of tools (used for businesses created before models existed)."""
    modules = set(modules)
    if "inventory" in modules and "services" in modules:
        return MIXED
    if "inventory" in modules or "locations" in modules:
        return GOODS
    return SERVICES


def module_problems(model, modules):
    """Plain-language reasons a set of tools does not fit the business, or an empty list."""
    modules = set(modules)
    label = lambda module: MODULES[module]["label"]
    rules = BUSINESS_MODELS[model]
    problems = []
    if not modules:
        return ["Choose at least one tool for your business."]
    not_allowed = sorted(modules - set(rules["modules"]), key=list(MODULES).index)
    if not_allowed:
        problems.append(f"{', '.join(label(m) for m in not_allowed)} cannot be used when you {rules['phrase']}. "
                        "Change what your business does to use them.")
    required = rules["requires"]
    if not modules & set(required):
        problems.append(f"Turn on {' or '.join(label(m) for m in required)}.")
    for module, needs in MODULE_NEEDS.items():
        if module in modules and not modules & set(needs):
            problems.append(f"{label(module)} needs {' or '.join(label(n) for n in needs)}. Turn it on as well.")
    return problems


def suggested_modules(model, sector_id, size):
    _, sector = SECTOR_INDEX[sector_id]
    allowed = BUSINESS_MODELS[model]["modules"]
    chosen = set(sector["modules"]) | set(SIZES[size]["modules"])
    return [module for module in MODULES if module in chosen and module in allowed]


def catalogue():
    """Everything the registration and settings screens need, in display order."""
    return {
        "models": [{"id": key, **value} for key, value in BUSINESS_MODELS.items()],
        "sizes": [{"id": key, "label": value["label"], "hint": value["hint"]} for key, value in SIZES.items()],
        "modules": [{"id": key, **value, "needs": list(MODULE_NEEDS.get(key, ()))} for key, value in MODULES.items()],
        "sectors": {model: [{**sector, "modules": {size: suggested_modules(model, sector["id"], size) for size in SIZES}}
                            for sector in sectors] for model, sectors in SECTORS.items()},
        "other_sectors": sorted(OTHER_SECTORS),
    }
