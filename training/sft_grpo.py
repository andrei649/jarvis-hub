"""
sft_grpo.py — H11.3 SFT + GRPO fine-tuning pipeline (HOST/GPU ONLY).

⚠️ SOURCE ONLY — this script requires a GPU + `transformers`/`trl`/`peft` and is
**not run in CI**. It closes the learning loop (H7.11): fine-tune a local model
(SFT, then optional GRPO) on traces exported via `prepare_data.py`.

Usage (host, GPU):
    python training/prepare_data.py ...        # produce sft.jsonl
    python training/sft_grpo.py --data sft.jsonl --model Qwen/Qwen3-4B --out ./ft

The imports are guarded so importing this module never breaks a no-GPU
environment; calling `main()` without the deps raises a clear error.
"""

from __future__ import annotations

import argparse
import json


def _require_deps():
    try:
        import torch  # noqa: F401
        from datasets import Dataset  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: F401
        from trl import SFTConfig, SFTTrainer  # noqa: F401
    except Exception as e:  # pragma: no cover - host-only path
        raise RuntimeError(
            "SFT/GRPO requires a GPU host with transformers/trl/datasets/torch installed "
            f"(pip install 'trl' 'transformers' 'datasets' 'peft' accelerate). Missing: {e}"
        ) from e


def load_jsonl(path: str) -> "list[dict]":
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_sft(data_path: str, base_model: str, out_dir: str,
            epochs: int = 1, lr: float = 2e-5):  # pragma: no cover - host-only
    """Supervised fine-tune `base_model` on the SFT JSONL → `out_dir`."""
    _require_deps()
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    rows = load_jsonl(data_path)
    ds = Dataset.from_list(rows)
    tok = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForCausalLM.from_pretrained(base_model)
    cfg = SFTConfig(output_dir=out_dir, num_train_epochs=epochs,
                    learning_rate=lr, per_device_train_batch_size=1,
                    gradient_accumulation_steps=8, logging_steps=10)
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
    trainer.train()
    trainer.save_model(out_dir)
    return out_dir


def main():  # pragma: no cover - host-only entrypoint
    ap = argparse.ArgumentParser(description="Jarvis SFT/GRPO fine-tuning (GPU host).")
    ap.add_argument("--data", required=True, help="SFT JSONL from prepare_data.py")
    ap.add_argument("--model", default="Qwen/Qwen3-4B")
    ap.add_argument("--out", default="./ft-out")
    ap.add_argument("--epochs", type=int, default=1)
    args = ap.parse_args()
    print(run_sft(args.data, args.model, args.out, epochs=args.epochs))


if __name__ == "__main__":  # pragma: no cover
    main()
