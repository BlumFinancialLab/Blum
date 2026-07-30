from __future__ import annotations

from dataclasses import dataclass

from .finrlx import QuantPolicyProposal


@dataclass(frozen=True)
class FinRLXOverlayResult:
    status: str
    applied: bool
    confidence_adjustment: float
    require_confirmation: bool
    preserved_blockers: tuple[str, ...]
    explanation: str

    def to_payload(self) -> dict:
        return {
            "status": self.status,
            "applied": self.applied,
            "confidence_adjustment": self.confidence_adjustment,
            "require_confirmation": self.require_confirmation,
            "preserved_blockers": list(self.preserved_blockers),
            "explanation": self.explanation,
        }


class FinRLXDecisionOverlay:
    """Evidence gate between a FinRL-X challenger and BLUM decisions."""

    def __init__(
        self,
        *,
        minimum_holdout: int = 100,
        minimum_accuracy: float = 0.52,
        maximum_adjustment: float = 0.05,
    ) -> None:
        self.minimum_holdout = max(30, int(minimum_holdout))
        self.minimum_accuracy = max(0.5, min(0.9, float(minimum_accuracy)))
        self.maximum_adjustment = max(0.0, min(0.05, float(maximum_adjustment)))

    def evaluate(
        self,
        *,
        baseline_direction: str,
        baseline_confidence: float,
        proposal: QuantPolicyProposal,
        deterministic_blockers: tuple[str, ...] | list[str] = (),
    ) -> FinRLXOverlayResult:
        blockers = tuple(dict.fromkeys(str(item) for item in deterministic_blockers))
        if blockers:
            return FinRLXOverlayResult(
                "BLOCKED_BY_DETERMINISTIC_AUTHORITY",
                False,
                0.0,
                True,
                blockers,
                "FinRL-X cannot bypass an existing data, risk, or execution blocker.",
            )
        if proposal.status != "SHADOW":
            return FinRLXOverlayResult(
                "SHADOW_UNAVAILABLE",
                False,
                0.0,
                False,
                (),
                "No validated shadow policy proposal is available.",
            )
        if (
            proposal.validation_sample_count < self.minimum_holdout
            or proposal.directional_accuracy is None
            or proposal.directional_accuracy < self.minimum_accuracy
            or proposal.mean_policy_net_r is None
            or proposal.mean_policy_net_r <= 0
            or proposal.regression_improvement is None
            or proposal.regression_improvement <= 0
        ):
            return FinRLXOverlayResult(
                "FROZEN_INSUFFICIENT_EVIDENCE",
                False,
                0.0,
                False,
                (),
                "FinRL-X remains shadow-only until chronological classification and regression evidence is positive.",
            )

        direction = str(baseline_direction).upper()
        proposal_direction = proposal.action
        if proposal.action == "TARGET_WEIGHTS":
            net_weight = sum(weight for _, weight in proposal.target_weights)
            proposal_direction = "LONG" if net_weight > 0 else "SHORT" if net_weight < 0 else "HOLD"
        aligned = proposal_direction == direction
        strength = min(
            1.0,
            max(0.0, abs(proposal.directional_score))
            * max(0.0, (proposal.directional_accuracy - 0.5) / 0.2),
        )
        adjustment = round(self.maximum_adjustment * strength * (1.0 if aligned else -1.0), 6)
        return FinRLXOverlayResult(
            "APPLIED_ALIGNMENT" if aligned else "APPLIED_DISAGREEMENT",
            True,
            adjustment,
            not aligned,
            (),
            (
                "Validated FinRL-X evidence aligns with the baseline direction."
                if aligned
                else "Validated FinRL-X evidence disagrees; confirmation is required and confidence is reduced."
            ),
        )
