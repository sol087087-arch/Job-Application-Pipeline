from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from job_pipeline.db.repository import Repository, hash_family_key
from job_pipeline.matching.policy import ApplyHistory, evaluate_reapply
from job_pipeline.matching.similarity import family_match_score, similarity, title_similarity


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FamilyLinkResult:
    family_id: int
    created: bool
    match_reason: str
    family_key: str
    description_similarity: float | None = None
    title_similarity: float | None = None
    match_score: float | None = None


def _best_existing_family_match(
    repository: Repository,
    *,
    company_id: int | None,
    company: str,
    title: str,
    location: str | None,
    description_text: str | None,
    source_job_id: str | None,
    normalized_url: str | None,
) -> tuple[object | None, str | None, float | None, float | None, float | None]:
    family_key = hash_family_key(company, title, location)
    family = repository.get_family_by_key(family_key)
    if family is not None:
        return family, "exact family key", None, None, 1.0

    families = repository.fetch_families_for_company(company_id)
    if not families:
        return None, None, None, None, None

    best_row = None
    best_reason = None
    best_desc_similarity = None
    best_title_similarity = None
    best_score = -1.0

    for family_row in families:
        title_sim = title_similarity(title, family_row["canonical_title"])
        location_sim = similarity(location, family_row["canonical_location"])
        desc_sim = None
        if description_text:
            latest_posting = repository.get_latest_snapshot_for_family(int(family_row["id"]))
            if latest_posting is not None:
                desc_sim = similarity(description_text, latest_posting["description_text"])
        score = family_match_score(
            company,
            title,
            location,
            str(family_row["canonical_company"] or ""),
            str(family_row["canonical_title"] or ""),
            str(family_row["canonical_location"] or ""),
        )
        if desc_sim is not None:
            score = max(score, (score * 0.7) + (desc_sim * 0.3))
        if source_job_id and repository.family_has_source_job_id(int(family_row["id"]), source_job_id):
            score = 1.0
        if normalized_url and repository.family_has_normalized_url(int(family_row["id"]), normalized_url):
            score = 1.0

        if score > best_score:
            best_score = score
            best_row = family_row
            best_reason = "fuzzy company/title/location/description match"
            best_desc_similarity = desc_sim
            best_title_similarity = title_sim

    if best_row is not None and best_score >= 0.7:
        return best_row, best_reason, best_desc_similarity, best_title_similarity, best_score
    return None, None, None, None, None


def link_job_family(
    repository: Repository,
    *,
    posting_id: int,
    company_id: int | None,
    company: str,
    title: str,
    location: str | None,
    description_text: str | None = None,
    source_job_id: str | None = None,
    normalized_url: str | None = None,
) -> FamilyLinkResult:
    family_key = hash_family_key(company, title, location)
    family, reason, desc_similarity, title_sim, match_score = _best_existing_family_match(
        repository,
        company_id=company_id,
        company=company,
        title=title,
        location=location,
        description_text=description_text,
        source_job_id=source_job_id,
        normalized_url=normalized_url,
    )

    now = utc_now()
    if family is None:
        family_id = repository.create_family(
            company_id=company_id,
            canonical_company=company,
            canonical_title=title,
            canonical_location=location,
            family_key=family_key,
            seen_at=now,
        )
        repository.attach_posting_to_family(posting_id, family_id)
        return FamilyLinkResult(
            family_id=family_id,
            created=True,
            match_reason="new family",
            family_key=family_key,
            description_similarity=None,
            title_similarity=None,
            match_score=None,
        )

    family_id = int(family["id"])
    repository.attach_posting_to_family(posting_id, family_id)
    repository.update_family_seen(family_id, now)
    repository.update_family_canonical(
        family_id,
        canonical_company=company,
        canonical_title=title,
        canonical_location=location,
    )
    return FamilyLinkResult(
        family_id=family_id,
        created=False,
        match_reason=reason or "existing family",
        family_key=family_key,
        description_similarity=desc_similarity,
        title_similarity=title_sim,
        match_score=match_score,
    )


def should_reapply(
    *,
    source_job_id: str | None,
    previous_source_job_id: str | None,
    same_family: bool,
    title_location_company_match: bool,
    description_similarity: float | None,
    days_since_last_application: int | None,
) -> str:
    history = ApplyHistory(
        same_source_job_id_submitted=bool(
            source_job_id
            and previous_source_job_id
            and str(source_job_id) == str(previous_source_job_id)
        ),
        same_family_applied_days_ago=days_since_last_application if same_family or title_location_company_match else None,
        similar_family_confidence=description_similarity or 0.0,
    )
    return evaluate_reapply(history).action
