# BLUM Finance 4B Release Report

## Release Policy

BLUM Finance 4B is promoted only when an immutable candidate improves over the
exact base revision on the untouched temporal test split and passes the
no-fabrication, structured-output, risk, invalidation, calibration and smoke-test
gates. A language-model evaluation does not prove trading alpha.

## Source Export

- BLUM Engine revision: `973fa4a3579c8b883372e96ed6e7a6e1c99e534a`
- Export ID: `1`
- Minimum training-value score: `70`
- Exported records: `521`
- Train / validation / test: `416 / 52 / 53`
- Dataset content SHA-256:
  `4cd60a2a44eabc185f6eceba5e2619aeb11ec437b89fe3cacc5cff240e52deaf`
- Archive SHA-256:
  `364c0f8c1b1653c22ccacbad45181fa1bdb828f2b95f290f2e220c13a4b17311`
- Lineages audited: `521`
- Cross-split lineage leakage: `0`
- Redaction and schema audit: `passed`

The export was generated through the explicit POST release boundary after the
deployed Space reported `api_ready=true`. No GET request triggered dataset
generation.

## Dataset Publication

- Repository:
  `Italianhype/Blum-Finance-Reasoning`
- Immutable revision:
  `76ad77699d498fc930daf02e452fe3ec8b490f90`
- Published files: `train.jsonl`, `validation.jsonl`, `test.jsonl`,
  `excluded.jsonl`, `manifest.json`, `README.md`
- Remote manifest SHA-256:
  `cc6ffd1f5d1d9ea070715dbaceeebf22a094e2329054e3bb38b590cacb405cc7`

The remote manifest was downloaded by immutable revision and compared byte for
byte with the audited local manifest.

## Training And Evaluation

Status: `blocked_before_job_creation`

The immutable `a10g-large` training job was submitted with a six-hour timeout,
encrypted `HF_TOKEN`, Trackio reporting and output repository
`Italianhype/Blum-Finance-4B-LoRA`. Hugging Face rejected the request before job
creation with HTTP `402`:

`Pre-paid credit balance is insufficient - add more credits to your account to use Jobs.`

No GPU job started and no training charge was incurred. The local M3 Pro has
18 GB unified memory and MPS available, but it was not used as a silent
substitute for the specified reproducible PEFT/TRL job: changing runtime,
quantization or training method would invalidate the agreed comparison.

No candidate score, adapter revision, merged model, GGUF artifact or alpha claim
is recorded. The guarded publisher will continue to reject the primary model
release until training, held-out evaluation, promotion and both smoke tests pass.

## Community Contribution Quarantine

- Repository: `Italianhype/Blum-Finance-Memory`
- Initial revision: `780c1c65668922a7d3360dcadf7f905d85d02957`
- Telemetry default: `disabled`
- Explicit consent required: `true`
- Automatic ingestion into active weights: `never`

## Verification

- Full Python suite: `630 passed`
- BLUM Finance focused suite: `32 passed`
- Next.js production build: `61/61 pages generated`
- Space deployment revision:
  `973fa4a3579c8b883372e96ed6e7a6e1c99e534a`
- Training job source: `model_release/training/hf_job.py`
- HF Jobs request: rejected before execution because account credits were
  insufficient
