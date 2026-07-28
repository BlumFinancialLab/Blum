from __future__ import annotations

import json
from typing import Callable, Literal

from pydantic import ValidationError

from .schemas import FinancialReasoningRequest, FinancialReasoningResponse


SYSTEM_PROMPT = """You are BLUM Finance, an evidence-bound financial reasoning model.
Use only the supplied point-in-time evidence. Separate supportive and contradictory
evidence. Never invent prices, returns, events or sources. Return one JSON object that
matches the requested schema. If evidence is insufficient, abstain explicitly."""


class BlumFinancePipeline:
    def __init__(
        self,
        model_id: str = "Italianhype/Blum",
        *,
        revision: str | None = None,
        runtime: Literal["transformers", "mlx"] = "transformers",
        generator: Callable[[list[dict[str, str]]], str] | None = None,
    ):
        self.model_id = model_id
        self.revision = revision
        self.runtime = runtime
        self._generator = generator
        self._pipeline = None
        self._mlx_model = None
        self._mlx_tokenizer = None

    def generate(
        self,
        request: FinancialReasoningRequest | dict,
    ) -> FinancialReasoningResponse:
        parsed_request = (
            request
            if isinstance(request, FinancialReasoningRequest)
            else FinancialReasoningRequest.model_validate(request)
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    parsed_request.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        raw = self._generator(messages) if self._generator else self._generate(messages)
        try:
            payload = _extract_json_object(raw)
            return FinancialReasoningResponse.model_validate(payload)
        except (ValueError, json.JSONDecodeError, ValidationError):
            return FinancialReasoningResponse(
                status="insufficient_evidence",
                thesis="The model output could not be validated against the BLUM Finance schema.",
                confidence=0,
                what_would_change_the_view=[
                    "Provide a schema-valid response grounded in the supplied evidence."
                ],
            )

    def _generate(self, messages: list[dict[str, str]]) -> str:
        if self.runtime == "mlx":
            return self._generate_with_mlx(messages)
        return self._generate_with_transformers(messages)

    def _generate_with_transformers(self, messages: list[dict[str, str]]) -> str:
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline(
                "text-generation",
                model=self.model_id,
                revision=self.revision,
                device_map="auto",
            )
        result = self._pipeline(
            messages,
            max_new_tokens=768,
            do_sample=False,
            return_full_text=False,
        )
        generated = result[0]["generated_text"]
        if isinstance(generated, list):
            generated = generated[-1]["content"]
        return str(generated)

    def _generate_with_mlx(self, messages: list[dict[str, str]]) -> str:
        try:
            from mlx_lm import generate, load
            from mlx_lm.sample_utils import make_sampler
        except ImportError as exc:
            raise RuntimeError(
                "MLX inference requires the 'mlx' optional dependencies on Apple Silicon."
            ) from exc
        if self._mlx_model is None or self._mlx_tokenizer is None:
            self._mlx_model, self._mlx_tokenizer = load(
                self.model_id,
                revision=self.revision,
                tokenizer_config={"trust_remote_code": True},
            )
        prompt = self._mlx_tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        return str(
            generate(
                self._mlx_model,
                self._mlx_tokenizer,
                prompt=prompt,
                max_tokens=768,
                sampler=make_sampler(temp=0.0),
                verbose=False,
            )
        )


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found.")
    return json.loads(stripped[start : end + 1])
