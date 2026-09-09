# AI product image library

The built-in image generation tool created 22 generic product illustrations in
`client/public/images/catalog/`. These are illustrative images, not photographs
of the exact brand, model, or variant being sold.

New products select a random matching image once, stored as a ProductImage.
Editing or refreshing a product does not shuffle its image. A supplied product
image URL or an image added through the images API replaces the generated image.
Existing real photographs are preserved by the backfill command.

The library covers the five current categories, with covers and padlocks also
available in their parent categories. Product names match whole words such as
`cable`, `charger`, `earbuds`, `mouse`, `keyboard`, `bulb`, `socket`, and `trowel`.
Covers and padlocks use their specialized category as a fallback. Unsupported
product types have no automatic image, avoiding unrelated illustrations.
Category API responses include an `image_pool` containing the available URLs.

To extend coverage, add generated PNG files to the public directory and a tuple
(category name, product keywords, asset filenames without extensions) to `POOLS`
in `server/apps/catalog/image_library.py`. There is no fixed pool size limit.
New categories require a matching library entry before images are assigned.
No live image API call or API key is needed when creating products.

To fill missing images and replace sample seed placeholders:

```sh
.venv/bin/python server/manage.py assign_catalog_images
```

Generation prompt template (built-in tool, one call per asset):

> Use case: product-mockup. Asset: [filename]. One square ecommerce product
> photograph of [subject], isolated on warm white background, soft studio shadows,
> centered three-quarter view with generous margins. Realistic generic unbranded
> product. No logos, text, watermark, other products or collage. Save image for
> project catalog use.

Subjects: black, blue, and transparent smartphone covers; brass, steel, and black
padlocks; white and black USB wall chargers; white and black USB-C cables; white
and black wireless earbuds; black and white mice; black and white keyboards;
white and warm-white LED bulbs; white and cream wall sockets; wooden-handle and
red-handle masonry trowels.
