from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from job_pipeline.db.repository import Repository
from job_pipeline.matching.policy import ApplyHistory, ReapplyDecision, evaluate_reapply


@dataclass(frozen=True)
class ApplyEligibility:
    posting_id: int
    action: str
    can_submit: bool
    reason: str
    question: str
    recommendation: str | None
    previous_application_id: int | None = None
    days_since_last_application: int | None = None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(value: str | None, run_date: date) -> int | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return (run_date - parsed.date()).days


def evaluate_apply_eligibility(repository: Repository, *, posting_id: int, run_date: date) -> ApplyEligibility:
    posting = repository.fetch_job_posting(posting_id)
    if posting is None:
        raise ValueError(f"Posting not found: {posting_id}")

    family_id = posting["family_id"]
    if family_id is None:
        return ApplyEligibility(
            posting_id=posting_id,
            action="apply",
            can_submit=True,
            reason="no linked family history",
            question="",
            recommendation=None,
        )

    previous_rows = repository.list_previous_applications(family_id=int(family_id), submitted_only=True, limit=1)
    if not previous_rows:
        return ApplyEligibility(
            posting_id=posting_id,
            action="apply",
            can_submit=True,
            reason="no previous submitted application in family",
            question="",
            recommendation=None,
        )

    previous = previous_rows[0]
    if int(previous["posting_id"]) == int(posting_id):
        decision = ReapplyDecision(
            action="blocked_recent_duplicate",
            question="This posting already has a submitted application record.",
            recommendation="do not submit automatically",
            reason="same posting already submitted",
            blocks_submit=True,
        )
    else:
        days = _days_since(previous["submitted_at"] or previous["created_at"], run_date)
        same_source_job_id = bool(
            posting["source_job_id"]
            and previous["previous_source_job_id"]
            and str(posting["source_job_id"]) == str(previous["previous_source_job_id"])
        )
        decision = evaluate_reapply(
            ApplyHistory(
                same_source_job_id_submitted=same_source_job_id,
                same_family_applied_days_ago=days,
                similar_family_confidence=1.0,
            )
        )
        return ApplyEligibility(
            posting_id=posting_id,
            action=decision.action,
            can_submit=not decision.blocks_submit and decision.action == "apply",
            reason=decision.reason,
            question=decision.question,
            recommendation=decision.recommendation,
            previous_application_id=int(previous["id"]),
            days_since_last_application=days,
        )

    return ApplyEligibility(
        posting_id=posting_id,
        action=decision.action,
        can_submit=False,
        reason=decision.reason,
        question=decision.question,
        recommendation=decision.recommendation,
        previous_application_id=int(previous["id"]),
        days_since_last_application=_days_since(previous["submitted_at"] or previous["created_at"], run_date),
    )
