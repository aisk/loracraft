"""Aspect ratio bucketing.

`make_bucket_resolutions` is adapted from kohya-ss/sd-scripts library/model_util.py (Apache-2.0,
see vendor/kohya/LICENSE and README.md), so that bucket shapes match what users expect from kohya.
Modified: takes one side length instead of a (width, height) pair, returns a sorted list.
"""

import math
from dataclasses import dataclass


def make_bucket_resolutions(max_reso: int, min_size: int = 512, max_size: int = 2048, divisible: int = 64):
    """All (width, height) pairs with area <= max_reso**2 and sides in [min_size, max_size]."""
    max_area = max_reso * max_reso
    resos = set()

    width = int(math.sqrt(max_area) // divisible) * divisible
    resos.add((width, width))

    width = min_size
    while width <= max_size:
        height = min(max_size, int((max_area // width) // divisible) * divisible)
        if height >= min_size:
            resos.add((width, height))
            resos.add((height, width))
        width += divisible

    return sorted(resos)


@dataclass(frozen=True)
class BucketAssignment:
    bucket: tuple[int, int]  # (width, height) the image is trained at
    resized: tuple[int, int]  # (width, height) after resizing, before cropping
    crop: tuple[int, int]  # (left, top) of the centre crop


def assign_bucket(width: int, height: int, buckets: list[tuple[int, int]]) -> BucketAssignment:
    """Pick the bucket with the closest aspect ratio, then resize to cover it and centre-crop."""
    ar = width / height
    bucket = min(buckets, key=lambda b: abs(math.log(b[0] / b[1]) - math.log(ar)))
    bw, bh = bucket

    scale = max(bw / width, bh / height)
    rw, rh = max(bw, round(width * scale)), max(bh, round(height * scale))
    return BucketAssignment(bucket=bucket, resized=(rw, rh), crop=((rw - bw) // 2, (rh - bh) // 2))
