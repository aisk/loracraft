"""Training configuration: the full, self-contained description of one run."""

from typing import Literal

from pydantic import BaseModel, Field


class TrainImage(BaseModel):
    path: str
    caption: str = ""


class SamplePrompt(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 24
    cfg_scale: float = 6.0
    seed: int = 0


class TrainConfig(BaseModel):
    # Model
    base_model: str
    vae: str | None = None
    prediction_type: Literal["epsilon", "v_prediction"] = "epsilon"
    zero_terminal_snr: bool = False

    # Output
    output_name: str = Field("lora", pattern=r"^[\w.-]+$")  # becomes part of a file name

    # Data
    images: list[TrainImage]
    resolution: int = 1024
    min_bucket_reso: int = 512
    max_bucket_reso: int = 2048
    bucket_reso_steps: int = 64
    repeats: int = 1
    shuffle_caption: bool = True
    keep_tokens: int = 1
    caption_dropout_rate: float = 0.0
    max_token_chunks: int = 3  # 3 chunks of 75 tokens, like kohya's max_token_length=225

    # Network
    network_dim: int = 16
    network_alpha: float = 8
    conv_dim: int | None = None
    conv_alpha: float | None = None
    network_dropout: float | None = None

    # Optimisation
    epochs: int = 10
    batch_size: int = 1
    gradient_accumulation_steps: int = 1
    optimizer: Literal["adamw", "prodigy"] = "adamw"
    unet_lr: float = 1e-4
    train_text_encoder: bool = False
    text_encoder_lr: float = 5e-5
    weight_decay: float = 0.01
    lr_scheduler: Literal["constant", "constant_with_warmup", "cosine", "cosine_with_restarts", "linear"] = "cosine"
    lr_warmup_steps: int = 0
    max_grad_norm: float = 1.0
    scale_weight_norms: float | None = None

    # Loss
    min_snr_gamma: float | None = 5.0
    debiased_estimation: bool = False
    scale_v_pred_loss_like_noise_pred: bool = False
    noise_offset: float | None = None
    adaptive_noise_scale: float | None = None

    # Runtime
    # fp16 is the default: on AMD RDNA2 it measured 3.3x faster than bf16 with identical losses.
    mixed_precision: Literal["no", "fp16", "bf16"] = "fp16"
    gradient_checkpointing: bool = True
    seed: int = 42

    # Checkpoints and samples
    save_every_n_epochs: int = 1
    sample_every_n_epochs: int = 1
    sample_prompts: list[SamplePrompt] = Field(default_factory=list)

    def steps_per_epoch(self, num_batches: int) -> int:
        return -(-num_batches // self.gradient_accumulation_steps)
