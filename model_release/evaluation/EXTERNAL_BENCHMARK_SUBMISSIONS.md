# BLUM Finance 4B External Benchmark Submission

## Immutable Candidate

- Model: `Italianhype/Blum-Finance-4B`
- Revision: `ad6f5cec7f729370d2976d8c78983521cb37ca83`
- Tag: `benchmark-submission-v1`
- Base model: `Qwen/Qwen3-4B`
- License: Apache-2.0
- Parameters: 4.0B
- Weights: merged BF16 Safetensors
- Library: Hugging Face Transformers
- Remote model code: not required with Transformers 4.57.6
- Intended task: evidence-bound financial reasoning

## Requested Independent Evaluations

### Vals AI

Requested suites:

1. CorpFin v2
2. Finance Agent v2
3. Vals Index finance components, if eligible

Vals AI runs proprietary evaluations independently. A public leaderboard score
cannot be self-published. New or custom models require contact with the Vals
team through `contact@vals.ai` or the Vals platform. The model should be
identified by the immutable Hub revision above.

### Scale Labs

Requested suite:

1. Professional Reasoning Benchmark - Finance

Scale Labs asks model providers to contact `leaderboards@scale.com`. To preserve
leaderboard integrity, the first featured run must occur before the organization
encounters the private prompts. BLUM has not downloaded or used hidden PRBench
evaluation prompts.

## Reproducible Inference Configuration

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = "Italianhype/Blum-Finance-4B"
revision = "ad6f5cec7f729370d2976d8c78983521cb37ca83"

tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    revision=revision,
    dtype=torch.bfloat16,
    device_map="auto",
)
```

For conversational evaluation, use the repository chat template. Disable
Qwen's reasoning envelope only when a benchmark requires answer-only output:

```python
prompt = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False,
)
```

Use each benchmark owner's required temperature, token budget and tool policy.
Do not substitute BLUM's internal evaluation settings for the official
methodology.

## Submission Message

Subject: `Open-weight finance model evaluation request — BLUM Finance 4B`

> BLUM Finance 4B is an Apache-2.0, Qwen3-based 4B open-weight model specialized
> in evidence-bound financial reasoning, contradiction handling, risk
> disclosure and explicit invalidation. We request independent evaluation of
> immutable revision
> `ad6f5cec7f729370d2976d8c78983521cb37ca83` from
> `Italianhype/Blum-Finance-4B`. The repository uses standard Transformers and
> merged BF16 Safetensors without custom model code. We will publish favorable
> or unfavorable results without altering them and will not claim trading alpha
> from language-model benchmark performance.

## Integrity Rules

- Never call a self-run result an official Vals or Scale score.
- Never tune on private or held-out leaderboard prompts.
- Keep the submitted revision immutable.
- Publish failures and confidence intervals.
- Keep language-model capability separate from paper-forward trading evidence.
