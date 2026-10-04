"""The Excel template for importing products. Its headings are exactly product_import.COLUMNS.

The first sheet ("Products") is the one imported, so it holds only headings (examples live on their own
sheet). Dropdowns list this business's own categories, brands and shelf compartments; new categories and
brands may still be typed in and are created on import. Shelves are never created: they must already exist.
"""
import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .product_import import COLUMNS, REQUIRED

ROWS = 1000  # rows prepared with dropdowns and formats
TEXT, MONEY, QUANTITY = "@", "#,##0.00", "General"
# heading → (width, number format, help text)
FIELDS = {
    "name": (34, TEXT, "Required. What the item is called, e.g. Oraimo Type-C cable. One row per sellable product or variant."),
    "category": (40, TEXT, "Required. The full path from the top-level category, each level separated by >: "
                           "Parent > Child > Grandchild > ... e.g. Mobile Accessories > Chargers > Car Chargers. "
                           "Any number of levels. Every level not yet in the system is created, parent first, exactly where it is written. "
                           "Letter case and extra spaces are ignored when matching."),
    "brand": (18, TEXT, "Optional. Choose from the list or type a new brand."),
    "description": (36, TEXT, "Optional short description."),
    "product_type": (16, TEXT, "STOCK_ITEM (kept on a shelf and sold) or SERVICE (work you do, no stock). Empty means STOCK_ITEM."),
    "variant_name": (20, TEXT, "Optional size, colour or model, e.g. 1m, Black, 45W. Empty means Standard."),
    "sku": (20, TEXT, "Required. Your unique code for this product or variant. Must not be used by any other product."),
    "barcode": (18, TEXT, "Optional. The number under the barcode. Must be unique. Typed as text so Excel keeps leading zeros."),
    "selling_price": (14, MONEY, "Required. Price of one sellable unit, more than 0."),
    "minimum_price": (14, MONEY, "Optional. Lowest price a cashier may accept when a customer bargains, per unit. "
                                 "Cannot be higher than selling_price. Empty or 0 means no bargaining without a manager."),
    "minimum_stock": (14, QUANTITY, "Optional. You are warned to restock when stock falls to this number. Empty means 0."),
    "target_stock": (14, QUANTITY, "Optional. How many you like to have after restocking. Not lower than minimum_stock. Empty means 0."),
    "opening_quantity": (16, QUANTITY, "Optional. Units of this product you already own now (per sellable unit, e.g. 10 cables). "
                                       "Must be empty for SERVICE rows. When more than 0, opening_unit_cost and preferred_shelf are required."),
    "opening_unit_cost": (16, MONEY, "What ONE sellable unit cost you to buy. Required, and more than 0, when opening_quantity is more than 0. "
                                     "Opening stock value = opening_quantity × opening_unit_cost."),
    "preferred_shelf": (18, TEXT, "The existing compartment code or label where this item is kept, from the Shelves list. "
                                  "Required when opening_quantity is more than 0; must be empty for SERVICE rows. Shelves are never created by an import."),
}
assert list(FIELDS) == COLUMNS
INK, SOFT, REQUIRED_FILL, OPTIONAL_FILL = "1F2937", "F3F4F6", "FDE68A", "DBEAFE"
SAMPLE_ROWS = [
    ["Oraimo Type-C cable", "Mobile Accessories > Cables", "Oraimo", "Braided fast-charging cable", "STOCK_ITEM", "1m",
     "ORAIMO-TCC-1M", "6974415130015", 300, 250, 3, 15, 10, 180, "AL1C1S1"],
    ["Oraimo Type-C cable", "Mobile Accessories > Cables", "Oraimo", "Braided fast-charging cable", "STOCK_ITEM", "2m",
     "ORAIMO-TCC-2M", "", 400, 350, 2, 10, 6, 240, "AL1C1S1"],
    ["Amaya fast wall charger", "Mobile Accessories > Chargers > Wall Chargers", "Amaya", "", "", "", "AMAYA-FWC", "", 350, 300, 2, 6, 4, 160, "AL1C2S1"],
    ["Screen protector (to order)", "Mobile Accessories > Screen Protectors", "", "", "STOCK_ITEM", "", "SP-GEN", "", 200, "", 0, 0, "", "", ""],
    ["Photocopy A4 black & white", "Services > Printing", "", "Per page", "SERVICE", "", "SRV-COPY-A4", "", 10, 10, "", "", "", "", ""],
]


def _style_header(cell, required):
    cell.font = Font(bold=True, color=INK)
    cell.fill = PatternFill("solid", fgColor=REQUIRED_FILL if required else OPTIONAL_FILL)
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    cell.border = Border(bottom=Side(style="medium", color=INK))


def business_lists():
    """This business's category paths, brands and exact compartments (code, description) for the dropdowns."""
    from apps.inventory.models import Shelf
    from .models import Brand, Category
    categories = {c.pk: c for c in Category.objects.filter(active=True)}

    def path(c):
        parts = []
        while c:
            parts.append(c.name)
            c = categories.get(c.parent_id)
        return " > ".join(reversed(parts))
    shelves = Shelf.objects.filter(active=True, is_virtual=False, zone__active=True, level__active=True, level__stack__active=True)
    return {
        "categories": sorted((path(c) for c in categories.values()), key=str.casefold),
        "brands": sorted(Brand.objects.filter(active=True).values_list("name", flat=True), key=str.casefold),
        "shelves": [(s.physical_label or s.code, f"{s.level.stack.display_name}, level {s.level.level_number}")
                    for s in shelves.select_related("level__stack").order_by("level__stack__display_name", "level__level_number", "position_in_level", "code")],
    }


def build_template(lists=None, sample=False):
    """The .xlsx template. lists defaults to this business's; sample=True also fills the Products sheet with SAMPLE_ROWS."""
    lists = lists if lists is not None else business_lists()
    book = Workbook()
    sheet = book.active
    sheet.title = "Products"
    for col, heading in enumerate(COLUMNS, start=1):
        width, fmt, help_text = FIELDS[heading]
        cell = sheet.cell(row=1, column=col, value=heading)
        _style_header(cell, heading in REQUIRED)
        cell.comment = Comment(help_text, "LinTech")
        sheet.column_dimensions[get_column_letter(col)].width = width
        for row in range(2, ROWS + 2):
            sheet.cell(row=row, column=col).number_format = fmt
    if sample:
        for r, values in enumerate(SAMPLE_ROWS, start=2):
            for col, value in enumerate(values, start=1):
                sheet.cell(row=r, column=col, value=value if value != "" else None)
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "B2"

    # Hidden lists behind the dropdowns.
    hidden = book.create_sheet("Lists")
    columns = {"Types": ["STOCK_ITEM", "SERVICE"], "Categories": lists["categories"], "Brands": lists["brands"],
               "Shelves": [code for code, _ in lists["shelves"]]}
    ranges = {}
    for col, (title, values) in enumerate(columns.items(), start=1):
        hidden.cell(row=1, column=col, value=title).font = Font(bold=True)
        for row, value in enumerate(values, start=2):
            hidden.cell(row=row, column=col, value=value)
        letter = get_column_letter(col)
        ranges[title] = f"Lists!${letter}$2:${letter}${max(len(values), 1) + 1}"
    hidden.sheet_state = "hidden"
    index = {heading: i for i, heading in enumerate(COLUMNS, start=1)}

    def rule(heading, validation):
        letter = get_column_letter(index[heading])
        validation.add(f"{letter}2:{letter}{ROWS + 1}")
        sheet.add_data_validation(validation)

    def dropdown(heading, source, strict, message):
        rule(heading, DataValidation(type="list", formula1=source, allow_blank=True, showErrorMessage=True,
                                     errorStyle="stop" if strict else "information", error=message, errorTitle="Check this value"))

    dropdown("product_type", ranges["Types"], True, "Choose STOCK_ITEM or SERVICE, or leave it empty.")
    if lists["categories"]:
        dropdown("category", ranges["Categories"], False, "This category is new: it will be created when you import.")
    if lists["brands"]:
        dropdown("brand", ranges["Brands"], False, "This brand is new: it will be created when you import.")
    if lists["shelves"]:
        dropdown("preferred_shelf", ranges["Shelves"], True, "Choose an existing compartment from the list, or leave it empty.")
    for heading in ("selling_price", "minimum_price", "minimum_stock", "target_stock", "opening_quantity", "opening_unit_cost"):
        rule(heading, DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=True, showErrorMessage=True,
                                     error="Enter a number of 0 or more (no text, no negative numbers).", errorTitle="Numbers only"))

    # Instructions.
    guide = book.create_sheet("How to fill")
    guide.column_dimensions["A"].width = 22
    guide.column_dimensions["B"].width = 12
    guide.column_dimensions["C"].width = 100
    guide["A1"] = "How to fill the Products sheet"
    guide["A1"].font = Font(bold=True, size=14, color=INK)
    steps = [
        "1. Fill one row per sellable product or variant on the 'Products' sheet. Do not rename, move or add headings in row 1.",
        "2. Yellow columns are required. Blue columns are optional. Hover over a heading to see its note.",
        "3. Save the file as .xlsx and upload it in the app: Products > Import spreadsheet.",
        "4. The app checks every row first and shows every mistake with its row and column. Nothing is saved until you confirm, "
        "and then all rows are saved together or none.",
        "5. Categories: write the full path from the top, each level separated by > : Parent > Child > Grandchild > ... "
        "(as many levels as you need).",
        "   e.g. Mobile Accessories > Chargers > Car Chargers. The first name is always a top-level category. Every level not yet in "
        "the system is created, parent first, exactly where it is written; existing levels are reused (case and spaces ignored).",
        "6. Opening stock: quantity and buying cost are per sellable unit. Positive stock needs a cost and an existing shelf compartment.",
        "7. Imported products are for stock management only: they are not visible or orderable online, so no photos are needed.",
        "8. Uploading the same file again is safe: rows already imported unchanged are skipped, never doubled.",
    ]
    for row, text in enumerate(steps, start=3):
        guide.cell(row=row, column=1, value=text)
    start = len(steps) + 5
    for col, title in enumerate(["Column", "Required?", "What to write"], start=1):
        _style_header(guide.cell(row=start, column=col, value=title), False)
    for offset, heading in enumerate(COLUMNS, start=1):
        guide.cell(row=start + offset, column=1, value=heading).font = Font(bold=True)
        guide.cell(row=start + offset, column=2, value="Yes" if heading in REQUIRED else "No")
        note = guide.cell(row=start + offset, column=3, value=FIELDS[heading][2])
        note.alignment = Alignment(wrap_text=True, vertical="top")
        if offset % 2:
            for col in (1, 2, 3):
                guide.cell(row=start + offset, column=col).fill = PatternFill("solid", fgColor=SOFT)
    if lists["shelves"]:
        row = start + len(COLUMNS) + 2
        guide.cell(row=row, column=1, value="Your shelf compartments").font = Font(bold=True, size=12)
        for offset, (code, name) in enumerate(lists["shelves"], start=1):
            guide.cell(row=row + offset, column=1, value=code)
            guide.cell(row=row + offset, column=3, value=name)

    # A worked example, on its own sheet so it is never imported by mistake.
    example = book.create_sheet("Example")
    for col, heading in enumerate(COLUMNS, start=1):
        _style_header(example.cell(row=1, column=col, value=heading), heading in REQUIRED)
        example.column_dimensions[get_column_letter(col)].width = FIELDS[heading][0]
        for r, values in enumerate(SAMPLE_ROWS, start=2):
            cell = example.cell(row=r, column=col, value=values[col - 1] if values[col - 1] != "" else None)
            cell.number_format = FIELDS[heading][1]
    example.cell(row=len(SAMPLE_ROWS) + 3, column=1,
                 value="Example only: this sheet is not imported. Fill the 'Products' sheet.").font = Font(italic=True, color="B91C1C")
    example.freeze_panes = "B2"

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
