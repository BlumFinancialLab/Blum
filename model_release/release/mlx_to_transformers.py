from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
from typing import Any

import numpy as np


MLX_LORA_KEY = re.compile(
    r"^(?P<module>model\.layers\.\d+\..+)\.lora_(?P<matrix>[ab])$"
)
MODEL_WEIGHT_KEY = re.compile(r"^(?P<module>model\.layers\.\d+\..+)\.weight$")


def mlx_key_to_peft_key(key: str) -> str:
    match = MLX_LORA_KEY.fullmatch(key)
    if not match:
        raise ValueError(f"Unsupported MLX LoRA key: {key}")
    matrix = match.group("matrix").upper()
    return f"base_model.model.{match.group('module')}.lora_{matrix}.weight"


def peft_lora_alpha(*, rank: int, mlx_scale: float) -> float:
    """Return PEFT alpha where alpha / rank equals MLX's explicit scale."""
    return float(rank * mlx_scale)


def scaled_delta(
    mlx_a: np.ndarray,
    mlx_b: np.ndarray,
    *,
    scale: float,
) -> np.ndarray:
    """Return an output-by-input delta matching MLX LoRALinear.fuse."""
    return scale * (mlx_b.T @ mlx_a.T)


def convert_adapter(
    *,
    mlx_adapter: Path,
    output_dir: Path,
    base_model: str,
    rank: int,
    scale: float,
) -> dict[str, Any]:
    from safetensors.numpy import load_file, save_file

    source = load_file(str(mlx_adapter))
    converted = {
        mlx_key_to_peft_key(key): np.ascontiguousarray(value.T)
        for key, value in source.items()
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    save_file(converted, str(output_dir / "adapter_model.safetensors"))
    target_modules = sorted(
        {
            match.group("module").rsplit(".", 1)[-1]
            for key in source
            if (match := MLX_LORA_KEY.fullmatch(key))
        }
    )
    layer_indexes = sorted(
        {
            int(match.group("module").split(".")[2])
            for key in source
            if (match := MLX_LORA_KEY.fullmatch(key))
        }
    )
    config = {
        "alpha_pattern": {},
        "auto_mapping": None,
        "base_model_name_or_path": base_model,
        "bias": "none",
        "fan_in_fan_out": False,
        "inference_mode": True,
        "init_lora_weights": True,
        "layer_replication": None,
        "layers_pattern": "layers",
        "layers_to_transform": layer_indexes,
        "loftq_config": {},
        "lora_alpha": peft_lora_alpha(rank=rank, mlx_scale=scale),
        "lora_dropout": 0.0,
        "megatron_config": None,
        "megatron_core": "megatron.core",
        "modules_to_save": None,
        "peft_type": "LORA",
        "r": rank,
        "rank_pattern": {},
        "revision": None,
        "target_modules": target_modules,
        "task_type": "CAUSAL_LM",
        "use_dora": False,
        "use_rslora": False,
    }
    (output_dir / "adapter_config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "tensor_count": len(converted),
        "target_modules": target_modules,
        "layers": layer_indexes,
        "lora_alpha": config["lora_alpha"],
    }


def merge_transformers_model(
    *,
    base_dir: Path,
    mlx_adapter: Path,
    output_dir: Path,
    scale: float,
) -> dict[str, Any]:
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    adapter = _load_adapter_torch(mlx_adapter)
    pending_modules = {
        match.group("module")
        for key in adapter
        if (match := MLX_LORA_KEY.fullmatch(key))
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    shards = sorted(base_dir.glob("model-*.safetensors"))
    if not shards:
        single = base_dir / "model.safetensors"
        shards = [single] if single.exists() else []
    if not shards:
        raise FileNotFoundError(f"No safetensors model shards found in {base_dir}")

    merged_modules: list[str] = []
    for shard in shards:
        tensors: dict[str, torch.Tensor] = {}
        with safe_open(shard, framework="pt", device="cpu") as source:
            for key in source.keys():
                tensor = source.get_tensor(key)
                match = MODEL_WEIGHT_KEY.fullmatch(key)
                module = match.group("module") if match else None
                if module in pending_modules:
                    a = adapter[f"{module}.lora_a"].float()
                    b = adapter[f"{module}.lora_b"].float()
                    delta = scale * (b.T @ a.T)
                    tensor = (tensor.float() + delta).to(dtype=tensor.dtype)
                    merged_modules.append(module)
                tensors[key] = tensor.contiguous()
        save_file(
            tensors,
            str(output_dir / shard.name),
            metadata={"format": "pt"},
        )
        del tensors

    missing = sorted(pending_modules - set(merged_modules))
    if missing:
        raise ValueError(f"Adapter modules absent from base model: {missing[:10]}")
    _copy_transformers_metadata(base_dir, output_dir)
    return {
        "shards": len(shards),
        "merged_modules": len(merged_modules),
        "missing_modules": missing,
    }


def _load_adapter_torch(path: Path) -> dict[str, Any]:
    from safetensors import safe_open

    with safe_open(path, framework="pt", device="cpu") as source:
        return {key: source.get_tensor(key) for key in source.keys()}


def _copy_transformers_metadata(base_dir: Path, output_dir: Path) -> None:
    allowed_suffixes = {".json", ".jinja", ".model", ".txt", ".py"}
    for source in base_dir.iterdir():
        if source.is_file() and source.suffix in allowed_suffixes:
            shutil.copy2(source, output_dir / source.name)
    config_path = output_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.pop("quantization", None)
    config.pop("quantization_config", None)
    config["_name_or_path"] = "Italianhype/Blum-Finance-4B"
    config["torch_dtype"] = "bfloat16"
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a BLUM MLX LoRA to PEFT and a merged Transformers model."
    )
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--mlx-adapter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--peft-output-dir", type=Path, required=True)
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B")
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--scale", type=float, default=20.0)
    args = parser.parse_args()
    adapter_result = convert_adapter(
        mlx_adapter=args.mlx_adapter,
        output_dir=args.peft_output_dir,
        base_model=args.base_model,
        rank=args.rank,
        scale=args.scale,
    )
    merge_result = merge_transformers_model(
        base_dir=args.base_dir,
        mlx_adapter=args.mlx_adapter,
        output_dir=args.output_dir,
        scale=args.scale,
    )
    print(
        json.dumps(
            {"adapter": adapter_result, "merged_model": merge_result},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
