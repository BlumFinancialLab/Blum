from __future__ import annotations

import json

from model_release.training.sanitize_dataset import sanitize_example


def test_sanitizer_removes_numbers_not_present_in_point_in_time_input() -> None:
    example = {
        "example_id": "example-1",
        "messages": [
            {"role": "system", "content": "Use supplied evidence."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "evidence": [
                            {"type": "technical", "value": "Momentum is 75.0."}
                        ]
                    }
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "watch",
                        "thesis": "Momentum is 75.0 but conviction is 70.9.",
                        "bull_case": ["Momentum is 75.0."],
                        "bear_case": [],
                        "risks": ["Risk remains elevated."],
                        "invalidation_conditions": ["Loss of support near 396.48."],
                        "confidence": 64,
                        "what_would_change_the_view": ["A close below 396.48."],
                    }
                ),
            },
        ],
    }

    sanitized, changes = sanitize_example(example)
    response = json.loads(sanitized["messages"][-1]["content"])

    assert "75.0" in response["thesis"]
    assert "70.9" not in response["thesis"]
    assert "396.48" not in json.dumps(response)
    assert response["confidence"] == 64
    assert changes == 3
    assert sanitized["messages"][:-1] == example["messages"][:-1]


def test_sanitizer_caps_unvalidated_confidence() -> None:
    example = {
        "messages": [
            {"role": "user", "content": '{"evidence":["High risk"]}'},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "watch",
                        "thesis": "Evidence is mixed.",
                        "bull_case": [],
                        "bear_case": ["High risk"],
                        "risks": ["High risk"],
                        "invalidation_conditions": ["Evidence deteriorates."],
                        "confidence": 100,
                        "what_would_change_the_view": ["Better evidence."],
                    }
                ),
            },
        ]
    }

    sanitized, changes = sanitize_example(example)
    response = json.loads(sanitized["messages"][-1]["content"])

    assert response["confidence"] == 70
    assert changes == 1
