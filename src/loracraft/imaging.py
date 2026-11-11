"""Image helpers shared by the server and the trainer. Keep this free of heavy imports."""

from PIL import Image, ImageOps


def to_rgb(image: Image.Image) -> Image.Image:
    """Upright RGB copy of `image`, with transparency flattened onto white.

    A plain `convert("RGB")` drops the alpha channel, which turns transparent areas black.
    """
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", image.size, "white"), image).convert("RGB")
    return image.convert("RGB")
