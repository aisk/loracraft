"""Dataset preparation: bucketing, latent caching, caption processing and batching."""

import random
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import torch
from PIL import Image, ImageOps

from ..imaging import to_rgb
from .bucketing import BucketAssignment, assign_bucket, make_bucket_resolutions
from .config import TrainConfig


@dataclass
class Item:
    path: str
    caption: str
    original_size: tuple[int, int]  # (height, width)
    assignment: BucketAssignment
    latent_params: torch.Tensor | None = None  # [8, h/8, w/8]: mean and logvar of the VAE posterior

    @property
    def bucket(self) -> tuple[int, int]:
        return self.assignment.bucket

    @property
    def crop_top_left(self) -> tuple[int, int]:
        left, top = self.assignment.crop
        return (top, left)


def _load_cropped(item: Item) -> torch.Tensor:
    with Image.open(item.path) as source:
        image = to_rgb(source)
    image = image.resize(item.assignment.resized, Image.LANCZOS)
    left, top = item.assignment.crop
    bw, bh = item.assignment.bucket
    image = image.crop((left, top, left + bw, top + bh))
    array = np.asarray(image, dtype=np.float32) / 127.5 - 1.0
    return torch.from_numpy(array).permute(2, 0, 1)


def prepare_items(config: TrainConfig) -> list[Item]:
    buckets = make_bucket_resolutions(
        config.resolution, config.min_bucket_reso, config.max_bucket_reso, config.bucket_reso_steps
    )
    items = []
    for entry in config.images:
        with Image.open(entry.path) as image:
            width, height = ImageOps.exif_transpose(image).size
        items.append(
            Item(
                path=entry.path,
                caption=entry.caption,
                original_size=(height, width),
                assignment=assign_bucket(width, height, buckets),
            )
        )
    return items


@torch.no_grad()
def cache_latents(items: list[Item], vae, device, on_progress=None) -> None:
    """Encode every image once. Keeps the posterior parameters so each step draws a fresh latent."""
    for index, item in enumerate(items):
        pixels = _load_cropped(item).unsqueeze(0).to(device, dtype=torch.float32)
        item.latent_params = vae.encode(pixels).latent_dist.parameters[0].cpu()
        if on_progress:
            on_progress(index + 1, len(items))


def sample_latents(parameters: torch.Tensor) -> torch.Tensor:
    mean, logvar = parameters.chunk(2, dim=1)
    std = torch.exp(0.5 * logvar.clamp(-30.0, 20.0))
    return mean + std * torch.randn_like(mean)


def process_caption(caption: str, config: TrainConfig, rng: random.Random) -> str:
    """Caption dropout and tag shuffling, keeping the first `keep_tokens` tags in place."""
    if config.caption_dropout_rate > 0 and rng.random() < config.caption_dropout_rate:
        return ""
    if not config.shuffle_caption:
        return caption
    tags = [t.strip() for t in caption.split(",") if t.strip()]
    fixed, rest = tags[: config.keep_tokens], tags[config.keep_tokens :]
    rng.shuffle(rest)
    return ", ".join(fixed + rest)


def make_batches(items: list[Item], config: TrainConfig, rng: random.Random) -> list[list[Item]]:
    """Group by bucket, shuffle, and split into batches. Called once per epoch."""
    by_bucket = defaultdict(list)
    for item in items:
        by_bucket[item.bucket].extend([item] * config.repeats)

    batches = []
    for bucket_items in by_bucket.values():
        rng.shuffle(bucket_items)
        for i in range(0, len(bucket_items), config.batch_size):
            batches.append(bucket_items[i : i + config.batch_size])
    rng.shuffle(batches)
    return batches


def tag_frequency(items: list[Item]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        for tag in item.caption.split(","):
            if tag.strip():
                counts[tag.strip()] += 1
    return dict(counts)
