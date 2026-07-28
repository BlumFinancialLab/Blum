from __future__ import annotations

import numpy as np

from model_release.release.mlx_to_transformers import (
    mlx_key_to_peft_key,
    peft_lora_alpha,
    scaled_delta,
)


def test_mlx_adapter_keys_map_to_peft_orientation() -> None:
    assert mlx_key_to_peft_key(
        "model.layers.20.self_attn.q_proj.lora_a"
    ) == "base_model.model.model.layers.20.self_attn.q_proj.lora_A.weight"
    assert mlx_key_to_peft_key(
        "model.layers.20.self_attn.q_proj.lora_b"
    ) == "base_model.model.model.layers.20.self_attn.q_proj.lora_B.weight"


def test_peft_alpha_preserves_mlx_scale() -> None:
    assert peft_lora_alpha(rank=8, mlx_scale=20.0) == 160.0


def test_fused_delta_matches_mlx_lora_equation() -> None:
    mlx_a = np.arange(24, dtype=np.float32).reshape(6, 4) / 100
    mlx_b = np.arange(20, dtype=np.float32).reshape(4, 5) / 100
    inputs = np.arange(12, dtype=np.float32).reshape(2, 6) / 10

    expected_output_delta = 20.0 * ((inputs @ mlx_a) @ mlx_b)
    fused_weight_delta = scaled_delta(mlx_a, mlx_b, scale=20.0)
    actual_output_delta = inputs @ fused_weight_delta.T

    np.testing.assert_allclose(
        actual_output_delta,
        expected_output_delta,
        rtol=1e-6,
        atol=1e-7,
    )
