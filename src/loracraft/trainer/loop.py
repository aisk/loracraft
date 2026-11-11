"""The training loop. One call to `run` executes one training run inside `run_dir`.

Run directory layout:
    config.json      input: a serialised TrainConfig
    events.jsonl     output: structured progress events
    checkpoints/     output: one .safetensors per saved epoch
    samples/         output: sample images per epoch
    stop             control: create this file to request a graceful stop
"""

import json
import math
import os
import random
import time
from collections import deque
from pathlib import Path

import torch
import torch.nn.functional as F
from diffusers import DDPMScheduler
from diffusers.optimization import get_scheduler

from ..vendor.kohya import train_functions as ktf
from ..vendor.kohya.lora import LoRANetwork
from . import data, sdxl
from .config import TrainConfig
from .events import EventSink

DTYPES = {"no": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}


def _build_optimizer(config: TrainConfig, params):
    if config.optimizer == "prodigy":
        from prodigyopt import Prodigy

        # Prodigy estimates the step size itself, so the configured learning rates are not used.
        for group in params:
            group["lr"] = 1.0
        return Prodigy(
            params, lr=1.0, weight_decay=config.weight_decay, use_bias_correction=True, safeguard_warmup=True
        )
    return torch.optim.AdamW(params, lr=config.unet_lr, weight_decay=config.weight_decay)


def _metadata(config: TrainConfig, items, epoch: int, step: int, total_steps: int, started_at: float) -> dict[str, str]:
    """kohya-compatible `ss_*` metadata, so other tools can read how the LoRA was trained."""
    base_name = Path(config.base_model).name
    meta = {
        "ss_network_module": "networks.lora",
        "ss_network_dim": config.network_dim,
        "ss_network_alpha": config.network_alpha,
        "ss_network_args": json.dumps(
            {
                k: str(v)
                for k, v in {"conv_dim": config.conv_dim, "conv_alpha": config.conv_alpha}.items()
                if v is not None
            }
        ),
        "ss_base_model_version": "sdxl_base_v1-0",
        "ss_v2": False,
        "ss_sd_model_name": base_name,
        "ss_vae_name": Path(config.vae).name if config.vae else None,
        "ss_output_name": config.output_name,
        "ss_resolution": f"({config.resolution}, {config.resolution})",
        "ss_enable_bucket": True,
        "ss_min_bucket_reso": config.min_bucket_reso,
        "ss_max_bucket_reso": config.max_bucket_reso,
        "ss_num_train_images": len(items) * config.repeats,
        "ss_batch_size_per_device": config.batch_size,
        "ss_gradient_accumulation_steps": config.gradient_accumulation_steps,
        "ss_gradient_checkpointing": config.gradient_checkpointing,
        "ss_num_epochs": config.epochs,
        "ss_epoch": epoch,
        "ss_steps": step,
        "ss_max_train_steps": total_steps,
        "ss_optimizer": config.optimizer,
        "ss_learning_rate": config.unet_lr,
        "ss_unet_lr": config.unet_lr,
        "ss_text_encoder_lr": config.text_encoder_lr if config.train_text_encoder else None,
        "ss_lr_scheduler": config.lr_scheduler,
        "ss_lr_warmup_steps": config.lr_warmup_steps,
        "ss_max_grad_norm": config.max_grad_norm,
        "ss_scale_weight_norms": config.scale_weight_norms,
        "ss_min_snr_gamma": config.min_snr_gamma,
        "ss_debiased_estimation": config.debiased_estimation,
        "ss_noise_offset": config.noise_offset,
        "ss_adaptive_noise_scale": config.adaptive_noise_scale,
        "ss_zero_terminal_snr": config.zero_terminal_snr,
        "ss_shuffle_caption": config.shuffle_caption,
        "ss_keep_tokens": config.keep_tokens,
        "ss_caption_dropout_rate": config.caption_dropout_rate,
        "ss_max_token_length": config.max_token_chunks * 75,
        "ss_mixed_precision": config.mixed_precision,
        "ss_seed": config.seed,
        "ss_cache_latents": True,
        "ss_training_started_at": started_at,
        "ss_training_finished_at": time.time(),
        "ss_tag_frequency": json.dumps({"dataset": data.tag_frequency(items)}),
        "modelspec.sai_model_spec": "1.0.0",
        "modelspec.architecture": "stable-diffusion-xl-v1-base/lora",
        "modelspec.implementation": "https://github.com/Stability-AI/generative-models",
        "modelspec.title": config.output_name,
        "modelspec.prediction_type": "v" if config.prediction_type == "v_prediction" else "epsilon",
        "loracraft_version": "0.1.0",
    }
    return {k: str(v) for k, v in meta.items() if v is not None}


def run(run_dir: Path) -> None:
    config = TrainConfig.model_validate_json((run_dir / "config.json").read_text(encoding="utf-8"))
    events = EventSink(run_dir)
    pid_file = run_dir / "pid"  # lets a restarted server find out whether this run is still going
    pid_file.write_text(str(os.getpid()))
    try:
        _run(run_dir, config, events)
    except Exception as exc:
        events.emit("error", message=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        events.close()
        pid_file.unlink(missing_ok=True)


def _run(run_dir: Path, config: TrainConfig, events: EventSink) -> None:
    checkpoint_dir = run_dir / "checkpoints"
    sample_dir = run_dir / "samples"
    checkpoint_dir.mkdir(exist_ok=True)
    sample_dir.mkdir(exist_ok=True)
    stop_flag = run_dir / "stop"

    device = torch.device("cuda")
    weight_dtype = DTYPES[config.mixed_precision]
    autocast_dtype = None if config.mixed_precision == "no" else weight_dtype
    started_at = time.time()

    rng = random.Random(config.seed)
    torch.manual_seed(config.seed)

    # --- Models ---
    events.emit("status", phase="loading_model")
    models = sdxl.load_models(config.base_model, config.vae, weight_dtype)

    # --- Data ---
    items = data.prepare_items(config)
    events.emit("status", phase="caching_latents", total=len(items))
    models.vae.to(device)
    data.cache_latents(items, models.vae, device, lambda done, total: events.emit("cache", done=done, total=total))
    models.vae.to("cpu")
    torch.cuda.empty_cache()

    models.unet.to(device)
    for text_encoder in models.text_encoders:
        text_encoder.to(device)

    # --- Network ---
    network = LoRANetwork(
        models.text_encoders if config.train_text_encoder else [],
        models.unet,
        lora_dim=config.network_dim,
        alpha=config.network_alpha,
        dropout=config.network_dropout,
        conv_lora_dim=config.conv_dim,
        conv_alpha=config.conv_alpha,
    )
    network.apply_to()
    network.to(device, dtype=torch.float32)

    if config.gradient_checkpointing:
        # Diffusers only checkpoints in training mode. The SDXL U-Net has no dropout, so this is safe.
        models.unet.enable_gradient_checkpointing()
        models.unet.train()
        if config.train_text_encoder:
            for text_encoder in models.text_encoders:
                text_encoder.gradient_checkpointing_enable()
                text_encoder.train()

    params = network.prepare_optimizer_params(
        config.text_encoder_lr if config.train_text_encoder else None, config.unet_lr
    )
    trainable = [p for group in params for p in group["params"]]
    optimizer = _build_optimizer(config, params)

    batches_per_epoch = len(data.make_batches(items, config, random.Random(0)))
    steps_per_epoch = config.steps_per_epoch(batches_per_epoch)
    total_steps = steps_per_epoch * config.epochs
    lr_scheduler = get_scheduler(
        config.lr_scheduler,
        optimizer,
        num_warmup_steps=config.lr_warmup_steps,
        num_training_steps=total_steps,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=config.mixed_precision == "fp16")

    noise_scheduler = DDPMScheduler(
        beta_start=0.00085,
        beta_end=0.012,
        beta_schedule="scaled_linear",
        num_train_timesteps=1000,
        clip_sample=False,
    )
    # Same order as kohya: the SNR table for loss weighting is taken before the zero-terminal-SNR
    # fix. Computing it afterwards gives SNR 0 at the last timestep (NaN weights with epsilon
    # prediction) and far smaller high-noise weights than every kohya-trained v-pred LoRA uses.
    ktf.prepare_scheduler_for_custom_training(noise_scheduler, device)
    if config.zero_terminal_snr:
        ktf.fix_noise_scheduler_betas_for_zero_terminal_snr(noise_scheduler)
    v_prediction = config.prediction_type == "v_prediction"

    events.emit(
        "start",
        total_steps=total_steps,
        steps_per_epoch=steps_per_epoch,
        epochs=config.epochs,
        num_images=len(items),
        buckets={f"{w}x{h}": sum(1 for i in items if i.bucket == (w, h)) for w, h in sorted({i.bucket for i in items})},
        lora_modules=len(network.unet_loras) + len(network.text_encoder_loras),
    )

    def save_checkpoint(epoch: int, step: int) -> None:
        path = checkpoint_dir / f"{config.output_name}-{epoch:06d}.safetensors"
        network.save_weights(str(path), torch.float16, _metadata(config, items, epoch, step, total_steps, started_at))
        events.emit("checkpoint", epoch=epoch, step=step, path=str(path))

    def generate_samples(epoch: int, step: int) -> None:
        if not config.sample_prompts:
            return
        events.emit("status", phase="sampling", epoch=epoch)
        network.eval()
        models.vae.to(device)
        models.vae.enable_tiling()
        for index, sp in enumerate(config.sample_prompts):
            image = sdxl.sample_image(
                models,
                sp.prompt,
                sp.negative_prompt,
                sp.width,
                sp.height,
                sp.steps,
                sp.cfg_scale,
                sp.seed,
                config.prediction_type,
                config.zero_terminal_snr,
                autocast_dtype,
                config.max_token_chunks,
            )
            path = sample_dir / f"e{epoch:03d}_p{index:02d}.png"
            image.save(path)
            events.emit("sample", epoch=epoch, step=step, prompt_index=index, path=str(path))
        models.vae.to("cpu")
        torch.cuda.empty_cache()
        network.train()

    # --- Loop ---
    generate_samples(0, 0)  # baseline without any training, to compare against
    events.emit("status", phase="training")
    network.train()
    step = 0
    recent_losses: deque[float] = deque(maxlen=100)
    stopped = False

    for epoch in range(1, config.epochs + 1):
        batches = data.make_batches(items, config, rng)
        optimizer.zero_grad(set_to_none=True)
        accumulated = 0.0

        for batch_index, batch in enumerate(batches):
            if stop_flag.exists():
                stopped = True
                break
            step_started = time.time()

            latents = data.sample_latents(torch.stack([item.latent_params for item in batch])).to(device)
            latents = latents * sdxl.VAE_SCALING_FACTOR

            noise = torch.randn_like(latents)
            if config.noise_offset:
                noise = ktf.apply_noise_offset(latents, noise, config.noise_offset, config.adaptive_noise_scale)

            timesteps = torch.randint(0, noise_scheduler.config.num_train_timesteps, (len(batch),), device=device)
            noisy_latents = noise_scheduler.add_noise(latents, noise, timesteps)
            if config.gradient_checkpointing:
                noisy_latents.requires_grad_(True)

            captions = [data.process_caption(item.caption, config, rng) for item in batch]

            with torch.autocast("cuda", dtype=autocast_dtype, enabled=autocast_dtype is not None):
                with torch.set_grad_enabled(config.train_text_encoder):
                    embeds, pooled = sdxl.encode_prompts(models, captions, config.max_token_chunks)
                time_ids = torch.cat(
                    [
                        sdxl.make_time_ids(
                            item.original_size, item.crop_top_left, item.bucket[::-1], device, embeds.dtype
                        )
                        for item in batch
                    ]
                )
                pred = models.unet(
                    noisy_latents.to(weight_dtype),
                    timesteps,
                    encoder_hidden_states=embeds,
                    added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
                ).sample

            target = noise_scheduler.get_velocity(latents, noise, timesteps) if v_prediction else noise
            loss = F.mse_loss(pred.float(), target.float(), reduction="none").mean([1, 2, 3])
            if config.min_snr_gamma:
                loss = ktf.apply_snr_weight(loss, timesteps, noise_scheduler, config.min_snr_gamma, v_prediction)
            if config.scale_v_pred_loss_like_noise_pred and v_prediction:
                loss = ktf.scale_v_prediction_loss_like_noise_prediction(loss, timesteps, noise_scheduler)
            if config.debiased_estimation:
                loss = ktf.apply_debiased_estimation(loss, timesteps, noise_scheduler, v_prediction)
            loss = loss.mean()

            if not math.isfinite(loss.item()):
                raise RuntimeError(f"Loss became {loss.item()} at step {step + 1}; try a lower learning rate or bf16.")

            scaler.scale(loss / config.gradient_accumulation_steps).backward()
            accumulated += loss.item() / config.gradient_accumulation_steps

            is_last = batch_index == len(batches) - 1
            if (batch_index + 1) % config.gradient_accumulation_steps != 0 and not is_last:
                continue

            if config.max_grad_norm:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(trainable, config.max_grad_norm)
            scaler.step(optimizer)
            scaler.update()
            lr_scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            if config.scale_weight_norms:
                network.apply_max_norm_regularization(config.scale_weight_norms, device)

            step += 1
            recent_losses.append(accumulated)
            group = optimizer.param_groups[-1]
            events.emit(
                "step",
                step=step,
                epoch=epoch,
                loss=accumulated,
                loss_avg=sum(recent_losses) / len(recent_losses),
                lr=group["lr"] * group.get("d", 1.0),  # Prodigy's effective LR is lr * d
                seconds=time.time() - step_started,
            )
            accumulated = 0.0

        if stopped:
            break

        is_final = epoch == config.epochs
        if is_final or (config.save_every_n_epochs and epoch % config.save_every_n_epochs == 0):
            save_checkpoint(epoch, step)
        if config.sample_every_n_epochs and (is_final or epoch % config.sample_every_n_epochs == 0):
            generate_samples(epoch, step)
            events.emit("status", phase="training")
        events.emit("epoch", epoch=epoch, step=step)

    events.emit("done", stopped=stopped, step=step, seconds=time.time() - started_at)
