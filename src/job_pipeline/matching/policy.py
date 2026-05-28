from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplyHistory:
    same_source_job_id_submitted: bool = False
    same_family_applied_days_ago: int | None = None
    similar_family_confidence: float = 0.0


@dataclass(frozen=True)
class ReapplyDecision:
    action: str
    question: str
    recommendation: str | None
    reason: str
    blocks_submit: bool = False


def evaluate_reapply(history: ApplyHistory) -> ReapplyDecision:
    """
    Returns a human-facing decision summary for possible reapply cases.
    """

    if history.same_source_job_id_submitted:
        return ReapplyDecision(
            action="blocked_recent_duplicate",
            question="This looks like the same posting/source job ID as a previous submission.",
            recommendation="do not submit automatically",
            reason="same source job id already submitted",
            blocks_submit=True,
        )

    if history.same_family_applied_days_ago is not None and history.same_family_applied_days_ago < 30:
        return ReapplyDecision(
            action="blocked_recent_duplicate",
            question=(
                f"A similar role in this family was applied to {history.same_family_applied_days_ago} days ago. "
                "Do not apply again before the 30-day cooldown."
            ),
            recommendation="wait until the 30-day cooldown has passed",
            reason="same family applied recently",
            blocks_submit=True,
        )

    if history.same_family_applied_days_ago is not None and history.same_family_applied_days_ago >= 30:
        return ReapplyDecision(
            action="ask_human",
            question=(
                f"A similar role in this family was applied to {history.same_family_applied_days_ago} days ago. "
                "It may be a repost or a meaningfully updated role. Apply again?"
            ),
            recommendation="apply again",
            reason="same family reopened after a month or more",
        )

    if history.similar_family_confidence >= 0.75:
        return ReapplyDecision(
            action="ask_human",
            question="This looks like a similar role in the same family. Apply again?",
            recommendation="review before reapplying",
            reason="high similarity across company/title/location",
        )

    return ReapplyDecision(
        action="apply",
        question="",
        recommendation=None,
        reason="no reapply concern",
    )


def should_auto_apply(history: ApplyHistory) -> str:
    return evaluate_reapply(history).action


def can_submit_without_reapply_risk(history: ApplyHistory) -> bool:
    return not evaluate_reapply(history).blocks_submit
