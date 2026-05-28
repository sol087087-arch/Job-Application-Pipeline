from __future__ import annotations

import re
from difflib import SequenceMatcher
from hashlib import sha256

from job_pipeline.text_utils import normalize_text


def text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def normalize_job_title(value: str | None) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"^(senior|sr|junior|jr|lead|principal|staff)\s+", "", text)
    text = re.sub(r"\s+(senior|sr|junior|jr|lead|principal|staff)\b", "", text)
    text = re.sub(r"\b(level\s*[0-9ivx]+)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity(left: str | None, right: str | None) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized and not right_normalized:
        return 1.0
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def title_similarity(left: str | None, right: str | None) -> float:
    return similarity(normalize_job_title(left), normalize_job_title(right))


def family_match_score(
    company: str | None,
    title: str | None,
    location: str | None,
    canonical_company: str | None,
    canonical_title: str | None,
    canonical_location: str | None,
) -> float:
    company_score = 1.0 if similarity(company, canonical_company) >= 0.95 else similarity(company, canonical_company)
    title_score = title_similarity(title, canonical_title)
    location_score = similarity(location, canonical_location)
    return (company_score * 0.35) + (title_score * 0.4) + (location_score * 0.25)
