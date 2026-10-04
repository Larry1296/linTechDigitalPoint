# Importing products from a spreadsheet

## Can I import my products from Excel or CSV?
Yes. On the **Products** page click **Import spreadsheet**, download the template, fill it in and upload it as .xlsx or .csv. {platform} checks every row first and shows what will happen before anything is saved, and a committed import is all-or-nothing. Files can be up to 5 MB and 5,000 rows.

## Which columns does the spreadsheet need?
Required: **name**, **category**, **selling_price**. Optional: **quantity**, **buying_price**, **sku**, **barcode**, **brand**, **minimum_price** (lowest price) and **minimum_stock** (restock level). The first row must be the headings. Common headings such as "Product", "Price", "Qty", "Cost", "BP" or "SP" are recognised. Write sub-categories as `Phones > Chargers`; missing categories and brands are created for you.

## What happens to products that already exist?
Products already in the system are skipped and left unchanged, and so are rows that repeat an earlier row in the same file. A product counts as existing when its SKU, barcode or name matches (names match regardless of capital letters and extra spaces). This means you can import the same file again safely. Importing never changes the price or adds stock to an existing product; use Receive stock for that.

## What does the quantity column mean?
The quantity is opening stock: stock your business already owns. It is valued against opening equity and is not recorded as a purchase from a supplier. Imported stock starts as "Not on a shelf yet"; move it onto real shelves with **Place on a shelf** on the product page. For new deliveries from a supplier, use **Receive stock** instead so the supplier and receipt are recorded.

## What if a row has no buying price or no SKU?
A blank SKU is generated automatically. A blank buying price is allowed, but that stock is flagged as uncosted until you enter one, because profit cannot be calculated without it.
