"""SDXL LoRA trainer. Runs as a separate process: `python -m loracraft.trainer <run_dir>`."""

import os

# MPS lacks some operators; this lets them run on the CPU instead of failing. PyTorch reads it
# at import, and this package is always imported before torch is.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
