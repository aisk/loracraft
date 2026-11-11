"""SDXL model loading, prompt encoding and sampling."""

from dataclasses import dataclass

import torch
from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
from transformers import CLIPTextModelWithProjection, CLIPTokenizer

CHUNK_TOKENS = 75
# Fixed rather than read from the VAE's config: a standalone VAE file is not recognised as SDXL by
# diffusers and would report the SD1.5 factor (0.18215).
VAE_SCALING_FACTOR = 0.13025


@dataclass
class SdxlModels:
    unet: UNet2DConditionModel
    vae: AutoencoderKL
    text_encoders: list[torch.nn.Module]  # [CLIP-L, OpenCLIP-bigG]
    tokenizers: list[CLIPTokenizer]


def load_models(checkpoint: str, vae_path: str | None, dtype: torch.dtype) -> SdxlModels:
    """Load a single-file SDXL checkpoint. The VAE always stays float32: the SDXL VAE overflows in fp16."""
    # Load in float32 and cast down afterwards, so the VAE keeps the checkpoint's full precision.
    pipe = StableDiffusionXLPipeline.from_single_file(checkpoint, torch_dtype=torch.float32)
    pipe.unet.to(dtype=dtype)
    pipe.text_encoder.to(dtype=dtype)
    pipe.text_encoder_2.to(dtype=dtype)
    vae = AutoencoderKL.from_single_file(vae_path, torch_dtype=torch.float32) if vae_path else pipe.vae

    models = SdxlModels(
        unet=pipe.unet,
        vae=vae,
        text_encoders=[pipe.text_encoder, pipe.text_encoder_2],
        tokenizers=[pipe.tokenizer, pipe.tokenizer_2],
    )
    for module in (models.unet, models.vae, *models.text_encoders):
        module.requires_grad_(False)
        module.eval()
    return models


def _tokenize_chunks(tokenizer: CLIPTokenizer, texts: list[str], max_chunks: int) -> torch.Tensor:
    """Tokenise into `[batch, chunks, 77]`, splitting long prompts into 75-token chunks like A1111/ComfyUI."""
    all_ids = [tokenizer(t, add_special_tokens=False).input_ids[: CHUNK_TOKENS * max_chunks] for t in texts]
    num_chunks = max(1, max(-(-len(ids) // CHUNK_TOKENS) for ids in all_ids))

    batch = []
    for ids in all_ids:
        chunks = []
        for i in range(num_chunks):
            piece = ids[i * CHUNK_TOKENS : (i + 1) * CHUNK_TOKENS]
            padding = [tokenizer.pad_token_id] * (CHUNK_TOKENS - len(piece))
            chunks.append([tokenizer.bos_token_id, *piece, tokenizer.eos_token_id, *padding])
        batch.append(chunks)
    return torch.tensor(batch, dtype=torch.long)


def encode_prompts(models: SdxlModels, texts: list[str], max_chunks: int = 3) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (prompt_embeds [B, 77*chunks, 2048], pooled_embeds [B, 1280])."""
    hidden_per_encoder = []
    pooled = None
    for tokenizer, text_encoder in zip(models.tokenizers, models.text_encoders, strict=True):
        ids = _tokenize_chunks(tokenizer, texts, max_chunks).to(text_encoder.device)
        b, n, length = ids.shape
        out = text_encoder(ids.reshape(b * n, length), output_hidden_states=True)
        # SDXL conditions on the penultimate layer of both encoders.
        hidden_per_encoder.append(out.hidden_states[-2].reshape(b, n * length, -1))
        if isinstance(text_encoder, CLIPTextModelWithProjection):
            pooled = out.text_embeds.reshape(b, n, -1)[:, 0]  # pooled output of the first chunk
    return torch.cat(hidden_per_encoder, dim=-1), pooled


def make_time_ids(original_size, crop_top_left, target_size, device, dtype) -> torch.Tensor:
    """SDXL micro-conditioning: (orig_h, orig_w, crop_top, crop_left, target_h, target_w)."""
    return torch.tensor([[*original_size, *crop_top_left, *target_size]], device=device, dtype=dtype)


@torch.no_grad()
def sample_image(
    models: SdxlModels,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg_scale: float,
    seed: int,
    prediction_type: str,
    zero_terminal_snr: bool,
    autocast_dtype: torch.dtype | None,
    max_chunks: int = 3,
):
    """Generate one image with whatever LoRA is currently hooked into the models."""
    from PIL import Image

    device = models.unet.device
    scheduler = EulerDiscreteScheduler(
        beta_start=0.00085,
        beta_end=0.012,
        beta_schedule="scaled_linear",
        num_train_timesteps=1000,
        prediction_type=prediction_type,
        rescale_betas_zero_snr=zero_terminal_snr,
        timestep_spacing="trailing" if zero_terminal_snr else "leading",
        steps_offset=0 if zero_terminal_snr else 1,
    )
    scheduler.set_timesteps(steps, device=device)

    with torch.autocast("cuda", dtype=autocast_dtype, enabled=autocast_dtype is not None):
        embeds, pooled = encode_prompts(models, [negative_prompt, prompt], max_chunks)
        time_ids = make_time_ids((height, width), (0, 0), (height, width), device, embeds.dtype).repeat(2, 1)

        generator = torch.Generator("cpu").manual_seed(seed)
        latents = torch.randn((1, 4, height // 8, width // 8), generator=generator).to(device)
        latents = latents * scheduler.init_noise_sigma

        for t in scheduler.timesteps:
            model_input = scheduler.scale_model_input(torch.cat([latents] * 2), t)
            pred = models.unet(
                model_input.to(models.unet.dtype),
                t,
                encoder_hidden_states=embeds,
                added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
            ).sample.float()
            uncond, cond = pred.chunk(2)
            latents = scheduler.step(uncond + cfg_scale * (cond - uncond), t, latents).prev_sample

    image = models.vae.decode(latents.float() / VAE_SCALING_FACTOR).sample
    image = (image[0].clamp(-1, 1) + 1) / 2
    array = (image.permute(1, 2, 0).cpu().numpy() * 255).round().astype("uint8")
    return Image.fromarray(array)
