# Vendored from kohya-ss/sd-scripts

Source: https://github.com/kohya-ss/sd-scripts
Commit: cb70b96858477e716a2096292ab8aab433277f38 (2026-10-26)
License: Apache License 2.0 (see `LICENSE` in this directory)

Every file here is a **modified** excerpt of the upstream file named below.

| File here | Upstream file | What was kept | Changes |
|---|---|---|---|
| `lora.py` | `networks/lora.py` | `LoRAModule`, the core of `LoRANetwork` | Dropped inference-only modules, block-wise dims/LR, LoRA+, regional LoRA. Keys are converted to SAI naming on save. Fixed in-place mutation of the class-level target list. |
| `sdxl_keys.py` | `library/sdxl_model_util.py`, `networks/lora.py` | `make_unet_conversion_map`, `convert_diffusers_to_sai_if_needed` | Returns a new dict instead of mutating; fixed use of an unbound variable. |
| `train_functions.py` | `library/custom_train_functions.py` | SNR weighting, v-prediction scaling, debiased estimation, zero terminal SNR, noise offset | Removed argparse and logging setup, pyramid noise and the other unused functions. |
| `hashing.py` | `library/model_io.py` | safetensors model hashes | None beyond imports. |

`make_bucket_resolutions` in `trainer/bucketing.py` is also adapted from upstream
(`library/model_util.py`); it lives next to the rest of the bucketing code rather than here.
