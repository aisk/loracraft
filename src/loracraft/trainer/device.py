"""Which accelerator to train on, and the few calls that differ between them."""

import contextlib

import torch


def pick_device() -> torch.device:
    """The GPU to train on: CUDA (which ROCm builds also answer to), else Apple's MPS."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    raise RuntimeError("PyTorch finds no GPU: training needs a CUDA, ROCm or Apple Silicon (MPS) build")


def autocast(device: torch.device, dtype: torch.dtype | None):
    """Mixed-precision context for `device`, or nothing when training in full precision."""
    if dtype is None:
        return contextlib.nullcontext()  # not every PyTorch accepts `autocast("mps")`, even disabled
    return torch.autocast(device.type, dtype=dtype)


def empty_cache(device: torch.device) -> None:
    """Hand memory that is no longer referenced back, so the next phase can use it."""
    if device.type == "cuda":
        torch.cuda.empty_cache()
    elif device.type == "mps":
        torch.mps.empty_cache()
