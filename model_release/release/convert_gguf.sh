#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: $0 MERGED_MODEL_DIR LLAMA_CPP_DIR LLAMA_CPP_COMMIT OUTPUT_GGUF" >&2
  exit 2
fi

model_dir="$1"
llama_dir="$2"
expected_commit="$3"
output_gguf="$4"
observed_commit="$(git -C "$llama_dir" rev-parse HEAD)"

if [[ "$observed_commit" != "$expected_commit" ]]; then
  echo "llama.cpp revision mismatch: expected $expected_commit, observed $observed_commit" >&2
  exit 3
fi

intermediate="${output_gguf%.gguf}.f16.gguf"
python3 "$llama_dir/convert_hf_to_gguf.py" \
  "$model_dir" \
  --outfile "$intermediate" \
  --outtype f16
"$llama_dir/build/bin/llama-quantize" \
  "$intermediate" \
  "$output_gguf" \
  Q4_K_M
rm -f "$intermediate"

test -s "$output_gguf"
shasum -a 256 "$output_gguf"
