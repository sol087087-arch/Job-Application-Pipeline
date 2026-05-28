from __future__ import annotations

from datetime import date, datetime, timezone

from job_pipeline.db.repository import HumanDecisionInput, Repository
from job_pipeline.matching.policy import ApplyHistory, evaluate_reapply
from job_pipeline.matching.similarity import family_match_score


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(value: str | None, run_date: date) -> int | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return (run_date - dt.date()).days


def _latest_previous_application(repository: Repository, family_id: int) -> object | None:
    rows = repository.list_previous_applications(family_id=family_id, submitted_only=True, limit=1)
    return rows[0] if rows else None


def sync_reapply_decision_queue(repository: Repository, run_date: date) -> int:
    created = 0
    for posting in repository.list_reapply_candidates():
        family_id = int(posting["family_id"])
        previous = _latest_previous_application(repository, family_id)
        if previous is None:
            continue

        previous_application_id = int(previous["id"])
        if int(previous["posting_id"]) == int(posting["id"]):
            continue

        if repository.human_decision_exists(
            posting_id=int(posting["id"]),
            related_application_id=previous_application_id,
            decision_type="possible_reapply",
        ):
            continue

        days_since_last_application = _days_since(previous["submitted_at"] or previous["created_at"], run_date)
        family_row = repository.fetch_family_by_id(family_id)
        similar_family_confidence = (
            family_match_score(
                posting["company"],
                posting["title"],
                posting["location"],
                family_row["canonical_company"],
                family_row["canonical_title"],
                family_row["canonical_location"],
            )
            if family_row is not None
            else 0.0
        )
        same_source_job_id_submitted = bool(
            posting["source_job_id"]
            and previous["previous_source_job_id"]
            and str(posting["source_job_id"]) == str(previous["previous_source_job_id"])
        )

        history = ApplyHistory(
            same_source_job_id_submitted=same_source_job_id_submitted,
            same_family_applied_days_ago=days_since_last_application,
            similar_family_confidence=similar_family_confidence,
        )
        decision = evaluate_reapply(history)
        if decision.blocks_submit:
            repository.record_application_event(
                application_id=previous_application_id,
                posting_id=int(posting["id"]),
                event_type="recent_duplicate_blocked",
                message=decision.question,
                data={
                    "decision_type": "recent_duplicate_blocked",
                    "family_id": family_id,
                    "days_since_last_application": days_since_last_application,
                    "similar_family_confidence": similar_family_confidence,
                    "same_source_job_id_submitted": same_source_job_id_submitted,
                    "recommendation": decision.recommendation,
                },
            )
            repository.update_job_posting_status(
                int(posting["id"]),
                "needs_human_decision",
                needs_human_decision=1,
                decision_reason=decision.reason,
            )
            continue

        if decision.action != "ask_human":
            continue

        question = decision.question
        if previous["submitted_at"]:
            question = f"{question} Previous application date: {previous['submitted_at']}."

        repository.insert_human_decision(
            HumanDecisionInput(
                posting_id=int(posting["id"]),
                related_application_id=previous_application_id,
                decision_type="possible_reapply",
                question=question,
                recommendation=decision.recommendation,
            )
        )
        repository.record_application_event(
            application_id=previous_application_id,
            posting_id=int(posting["id"]),
            event_type="needs_human_decision",
            message=question,
            data={
                "decision_type": "possible_reapply",
                "family_id": family_id,
                "days_since_last_application": days_since_last_application,
                "similar_family_confidence": similar_family_confidence,
                "same_source_job_id_submitted": same_source_job_id_submitted,
            },
        )
        created += 1

    return created
