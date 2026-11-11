import random

from loracraft.trainer.bucketing import assign_bucket, make_bucket_resolutions
from loracraft.trainer.config import TrainConfig
from loracraft.trainer.data import process_caption
from loracraft.vendor.kohya.sdxl_keys import convert_diffusers_to_sai


def test_buckets_cover_common_shapes():
    buckets = make_bucket_resolutions(1024)
    assert (1024, 1024) in buckets and (832, 1216) in buckets and (1216, 832) in buckets
    assert all(w * h <= 1024 * 1024 and w % 64 == 0 and h % 64 == 0 for w, h in buckets)


def test_assign_bucket_covers_and_centres():
    a = assign_bucket(2000, 3000, make_bucket_resolutions(1024))
    assert a.bucket == (832, 1216)
    assert a.resized[0] >= 832 and a.resized[1] >= 1216
    assert a.crop == ((a.resized[0] - 832) // 2, (a.resized[1] - 1216) // 2)


def test_caption_shuffle_keeps_leading_tokens():
    config = TrainConfig(base_model="x", images=[], keep_tokens=2)
    out = process_caption("trigger, 1girl, a, b, c, d", config, random.Random(0))
    tags = out.split(", ")
    assert tags[:2] == ["trigger", "1girl"] and sorted(tags[2:]) == ["a", "b", "c", "d"]


def test_lora_keys_use_sai_names():
    keys = convert_diffusers_to_sai(
        {
            "lora_unet_down_blocks_1_attentions_0_transformer_blocks_0_attn1_to_q.alpha": 1,
            "lora_unet_mid_block_attentions_0_proj_in.alpha": 1,
            "lora_unet_up_blocks_0_attentions_2_transformer_blocks_9_ff_net_2.lora_up.weight": 1,
            "lora_te1_text_model_encoder_layers_0_mlp_fc1.alpha": 1,
        }
    )
    assert list(keys) == [
        "lora_unet_input_blocks_4_1_transformer_blocks_0_attn1_to_q.alpha",
        "lora_unet_middle_block_1_proj_in.alpha",
        "lora_unet_output_blocks_2_1_transformer_blocks_9_ff_net_2.lora_up.weight",
        "lora_te1_text_model_encoder_layers_0_mlp_fc1.alpha",
    ]


def test_loss_weights_stay_finite_with_zero_terminal_snr():
    import torch
    from diffusers import DDPMScheduler

    from loracraft.vendor.kohya import train_functions as ktf

    scheduler = DDPMScheduler(beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear", clip_sample=False)
    # The order used by the training loop, which is kohya's.
    ktf.prepare_scheduler_for_custom_training(scheduler, "cpu")
    ktf.fix_noise_scheduler_betas_for_zero_terminal_snr(scheduler)

    assert scheduler.alphas_cumprod[-1] == 0  # the noise schedule itself does reach pure noise
    timesteps = torch.tensor([0, 500, 999])
    for v_prediction in (False, True):
        weighted = ktf.apply_snr_weight(torch.ones(3), timesteps, scheduler, 5.0, v_prediction)
        assert torch.isfinite(weighted).all() and (weighted > 0).all()
