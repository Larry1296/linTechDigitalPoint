# Importing products from a spreadsheet

## Can I import my products from Excel or CSV?
Yes. On the **Products** page click **Download Excel template**, fill in one row per product or variant on its **Products** sheet, then click **Import spreadsheet** and upload it as .xlsx (or a .csv with the same headings). {platform} checks every row first and shows what will happen before anything is saved, and a committed import is all-or-nothing. Files can be up to 5 MB and 5,000 rows. Keep the file: next time just add new rows at the bottom and upload it again.

## Which columns does the spreadsheet need?
The template has one column for each field of the Add Product form, and each row is saved exactly as that form would save it. Required: **name**, **category**, **selling_price**. Optional: **brand**, **description**, **product_type** (STOCK_ITEM or SERVICE), **variant_name**, **pack_size** and **piece_name** (for items sold in packs), **sku**, **barcode**, **minimum_price** (bargaining guide), **service_cost** (services only), **minimum_stock**, **target_stock**, **opening_quantity**, **opening_unit_cost** and **preferred_shelf** (shops that use shelves). Hover over a heading in the template to see its note; the **How to fill** sheet explains every column and the **Example** sheet shows filled rows. Do not rename the headings in row 1.

## How do I write categories and sub-categories?
Write the full path from the top, each level separated by `>`: `Mobile Accessories > Chargers > Car Chargers`, with as many levels as you need. Levels that already exist are reused (capital letters and extra spaces are ignored). Every level that does not exist yet is created, parent first, exactly where you wrote it, just as if you had added it with **New category** in the form. New brands are created too. Shelves are never created by an import.

## What happens to products that already exist?
A row whose SKU or barcode is already in the system is skipped and changes nothing, so uploading the same file again never doubles products or stock. Importing never changes the price or adds stock to an existing product: edit it on its product page, or use Receive stock.

## What does the opening quantity mean?
opening_quantity is stock your business already owns. It is valued against opening equity and is not recorded as a purchase or money owed to a supplier. Put opening_unit_cost as the buying price of one item. For items sold in packs, count the pieces and give the price of one piece, as in the form: 500 sheets sold 2 for a price become 250 packs. Without a preferred_shelf the stock is kept as "Not on a shelf yet"; move it with **Place on a shelf** on the product page. For new deliveries from a supplier, use **Receive stock** instead.

## What if a row has no buying price or no SKU?
A blank SKU is made from the brand, name and variant, the same code the Add Product form suggests (Oraimo · Type-C cable · 1m becomes ORAIMO-TCC-1M). A blank buying price is allowed: that stock is marked cost pending until you enter the price, because profit cannot be worked out without it.

## Are imported products shown in the online shop?
No. Imported products are for stock management only and are not visible or orderable online, so no photos are needed. Add photos and publish a product from its product page if you want it online.
