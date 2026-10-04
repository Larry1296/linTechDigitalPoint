"""Business logo processing: transparent background, tight crop, two contrast-safe versions.

Every upload becomes two PNGs of the same design:
- ``light``: for white surfaces (receipts, email, settings), with near-white parts darkened;
- ``dark``: for the dark navigation bar, with near-black/navy parts turned white.
Brand colours that already contrast with the surface are never changed.
"""
from io import BytesIO
import warnings
from django.core.files.base import ContentFile
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError
from rest_framework import serializers

LOGO_BOX = (600, 240)
WORK_BOX = (1000, 400)
DARK_SURFACE = (8, 29, 58)       # --chrome: the navigation bar in both themes
LIGHT_SURFACE = (255, 255, 255)  # receipts and email
DARK_INK = (16, 33, 61)          # --text: what near-white parts become on light surfaces
TOLERANCE = 40


def _luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _edge_pixels(image):
    width, height = image.size
    points = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    points += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    return points


def _close(a, b, tolerance=TOLERANCE):
    return sum(abs(x - y) for x, y in zip(a[:3], b[:3])) <= tolerance


def _saturation(rgb):
    high, low = max(rgb[:3]), min(rgb[:3])
    return 0 if high == 0 else (high - low) / high


def remove_background(image):
    """Makes a plain white, grey or black background transparent, including inside letters.

    Only neutral backgrounds are removed (the usual box a JPEG or screenshot adds). A coloured
    background is part of the brand, so the logo keeps it and shows as a badge.
    """
    edges = _edge_pixels(image)
    pixels = image.load()
    if sum(1 for point in edges if pixels[point][3] < 250) > len(edges) * 0.2:
        return image  # Already transparent: the designer's own cut-out is kept.
    colours = {}
    for point in edges:
        key = tuple(v // 8 * 8 for v in pixels[point][:3])
        colours[key] = colours.get(key, 0) + 1
    background = max(colours, key=colours.get)
    if sum(1 for point in edges if _close(pixels[point], background)) < len(edges) * 0.6:
        return image  # No single background colour (e.g. a photo): leave it as it is.
    if _saturation(background) > 0.2:
        return image  # Coloured background: part of the brand.
    # Colour key with soft edges: close to the background -> clear, far -> solid, between -> partly clear.
    red, green, blue = ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, background)).split()
    distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    key = distance.point(lambda v: 0 if v <= 24 else 255 if v >= 72 else (v - 24) * 255 // 48)
    result = image.copy()
    result.putalpha(ImageChops.multiply(image.getchannel("A"), key))
    return result


def trim(image):
    """Crops empty (transparent) margins so the design itself fills the space.

    A thin frame along an edge (a screenshot's border, say) is not part of the design: a run of
    almost-full lines at an edge, followed by an empty gap, is ignored so it cannot stop the crop.
    """
    solid = image.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    width, height = solid.size
    band = max(3, round(min(width, height) * 0.02))
    filled = lambda box, length: solid.crop(box).histogram()[255] / length
    rows = lambda y: filled((0, y, width, y + 1), width)
    cols = lambda x: filled((x, 0, x + 1, height), height)
    draw = ImageDraw.Draw(solid)
    for lines, size, step, line in ((rows, height, 1, lambda y: [(0, y), (width - 1, y)]),
                                    (rows, height, -1, lambda y: [(0, y), (width - 1, y)]),
                                    (cols, width, 1, lambda x: [(x, 0), (x, height - 1)]),
                                    (cols, width, -1, lambda x: [(x, 0), (x, height - 1)])):
        start = 0 if step == 1 else size - 1
        frame = []
        position = start
        while len(frame) <= band and 0 <= position < size and lines(position) > 0.8:
            frame.append(position)
            position += step
        if frame and len(frame) <= band and 0 <= position < size and lines(position) < 0.05:
            for index in frame:
                draw.line(line(index), fill=0)
    box = solid.getbbox()
    return image.crop(box) if box else image


def fit(image, box=LOGO_BOX):
    """Scales up or down so the logo fills the box without distortion."""
    scale = min(box[0] / image.width, box[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image if size == image.size else image.resize(size, Image.Resampling.LANCZOS)


def for_surface(image, surface, ink, minimum=1.6):
    """Recolours only the parts that would disappear on the surface.

    A part is recoloured only when it sits directly on the surface (touches transparency);
    parts enclosed by the logo's own colours, like a white dot in a green badge, stay as designed.
    """
    width, height = image.size
    data = list(image.getdata())
    low = Image.new("L", image.size)
    low.putdata([128 if a > 16 and _contrast((r, g, b), surface) < minimum else 0 for r, g, b, a in data])
    clear = image.getchannel("A").point(lambda v: 255 if v <= 16 else 0).filter(ImageFilter.MaxFilter(3))
    low_values, clear_values = list(low.getdata()), list(clear.getdata())
    for index, value in enumerate(low_values):
        if value == 128 and clear_values[index] and low.getpixel((index % width, index // width)) == 128:
            ImageDraw.floodfill(low, (index % width, index // width), 255, thresh=0)
    reached = low.getdata()
    result = image.copy()
    result.putdata([(*ink, a) if reached[i] == 255 else (r, g, b, a) for i, (r, g, b, a) in enumerate(data)])
    return result


def png(image, name):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return ContentFile(output.getvalue(), name=name)


def process(upload):
    """Returns (light, dark) PNG files for an uploaded logo, or raises a friendly validation error."""
    if not upload:
        raise serializers.ValidationError({"logo": "Choose a logo image to upload."})
    if upload.size > 5 * 1024 * 1024:
        raise serializers.ValidationError({"logo": "Choose a logo smaller than 5 MB."})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError("format")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail(WORK_BOX, Image.Resampling.LANCZOS)
        image = fit(trim(remove_background(image)))
        return (png(for_surface(image, LIGHT_SURFACE, DARK_INK), "logo.png"),
                png(for_surface(image, DARK_SURFACE, LIGHT_SURFACE, minimum=2.2), "logo.png"))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError({"logo": "Upload a JPEG, PNG or WebP image of your logo."})
