from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_pipeline.db.connection import connect, initialize_database
from job_pipeline.text_utils import normalize_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value: str | None) -> str:
    return normalize_text(value).rstrip("/")


def hash_family_key(company: str, title: str, location: str | None) -> str:
    import hashlib

    payload = "|".join([normalize_text(company), normalize_text(title), normalize_text(location)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JobPostingInput:
    source: str
    company: str
    title: str
    url: str
    location: str | None = None
    source_job_id: str | None = None
    apply_url: str | None = None
    language: str = "en"
    source_priority: int = 100
    repost_of_application_id: int | None = None
    raw_json_path: str | None = None


@dataclass(frozen=True)
class ApplicationInput:
    posting_id: int
    snapshot_id: int
    family_id: int | None = None
    company_id: int | None = None
    status: str = "created"
    submission_method: str | None = None
    submitted_at: str | None = None
    email_used: str | None = None
    application_url: str | None = None
    confirmation_type: str | None = None
    confirmation_text: str | None = None
    confirmation_url: str | None = None
    confirmation_screenshot_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ResumeVariantInput:
    application_id: int
    variant_name: str
    base_resume_version: str
    resume_json_path: str
    resume_pdf_path: str | None
    resume_sha256: str
    target_title: str | None = None
    resume_docx_path: str | None = None
    resume_text_path: str | None = None
    tailoring_model: str | None = None
    tailoring_prompt_hash: str | None = None
    truth_profile_hash: str | None = None
    truth_guard_report_path: str | None = None
    diff_summary_path: str | None = None
    tailoring_score: float | None = None


@dataclass(frozen=True)
class SubmissionArtifactInput:
    application_id: int
    artifact_type: str
    path: str | None = None
    text_value: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class HumanDecisionInput:
    posting_id: int
    related_application_id: int | None
    decision_type: str
    question: str
    recommendation: str | None = None
    user_decision: str | None = None
    decided_at: str | None = None


@dataclass(frozen=True)
class EmailMessageInput:
    classification: str
    application_id: int | None = None
    gmail_message_id: str | None = None
    thread_id: str | None = None
    subject: str | None = None
    sender: str | None = None
    sender_domain: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    body_path: str | None = None
    action_required: int = 0
    visible_to_user: int = 0


@dataclass(frozen=True)
class PreviousApplicationQuery:
    company_id: int | None = None
    family_id: int | None = None
    posting_id: int | None = None
    limit: int = 20


class Repository:
    def __init__(self, db_path: str | Path, schema_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.connection = connect(self.db_path)
        if schema_path is not None:
            schema_sql = Path(schema_path).read_text(encoding="utf-8")
            initialize_database(self.connection, schema_sql)

    def close(self) -> None:
        self.connection.close()

    def upsert_company(
        self,
        name: str,
        *,
        website: str | None = None,
        greenhouse_token: str | None = None,
        lever_token: str | None = None,
    ) -> int:
        normalized_name = normalize_text(name)
        now = utc_now()
        row = self.connection.execute(
            "SELECT id FROM companies WHERE normalized_name = ?",
            (normalized_name,),
        ).fetchone()
        if row:
            company_id = int(row["id"])
            self.connection.execute(
                """
                UPDATE companies
                SET name = ?, website = COALESCE(?, website), greenhouse_token = COALESCE(?, greenhouse_token),
                    lever_token = COALESCE(?, lever_token), updated_at = ?
                WHERE id = ?
                """,
                (name, website, greenhouse_token, lever_token, now, company_id),
            )
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO companies (
                  name, normalized_name, website, greenhouse_token, lever_token, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, normalized_name, website, greenhouse_token, lever_token, now, now),
            )
            company_id = int(cursor.lastrowid)
        self.connection.commit()
        return company_id

    def insert_job_posting(self, posting: JobPostingInput, *, company_id: int | None = None) -> int:
        now = utc_now()
        normalized_url = normalize_url(posting.url)
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO job_postings (
              company_id, source, source_job_id, company, title, location, language, url, normalized_url,
              apply_url, source_priority, status, first_seen_at, last_seen_at, repost_of_application_id,
              created_at, updated_at, raw_json_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                posting.source,
                posting.source_job_id,
                posting.company,
                posting.title,
                posting.location,
                posting.language,
                posting.url,
                normalized_url,
                posting.apply_url,
                posting.source_priority,
                now,
                now,
                posting.repost_of_application_id,
                now,
                now,
                posting.raw_json_path,
            ),
        )
        if cursor.lastrowid:
            posting_id = int(cursor.lastrowid)
        else:
            row = self.connection.execute(
                """
                SELECT id FROM job_postings
                WHERE normalized_url = ?
                   OR (source = ? AND source_job_id IS NOT NULL AND source_job_id = ?)
                LIMIT 1
                """,
                (normalized_url, posting.source, posting.source_job_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert job posting")
            posting_id = int(row["id"])
            self.connection.execute(
                "UPDATE job_postings SET last_seen_at = ?, updated_at = ? WHERE id = ?",
                (now, now, posting_id),
            )
        self.connection.commit()
        return posting_id

    def insert_job_snapshot(
        self,
        posting_id: int,
        *,
        title: str,
        company: str,
        description_text: str,
        location: str | None = None,
        fetched_at: str | None = None,
        description_similarity_to_previous: float | None = None,
        change_ratio: float | None = None,
        requirements_json: Any | None = None,
        responsibilities_json: Any | None = None,
        apply_url: str | None = None,
        extracted_keywords_json: Any | None = None,
        raw_html_path: str | None = None,
        raw_text_path: str | None = None,
        raw_json_path: str | None = None,
    ) -> int:
        fetched_at = fetched_at or utc_now()
        description_hash = sha256_text(description_text)
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO job_snapshots (
              posting_id, fetched_at, title, company, location, description_text, description_hash,
              description_similarity_to_previous, change_ratio, requirements_json, responsibilities_json,
              apply_url, extracted_keywords_json, raw_html_path, raw_text_path, raw_json_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                posting_id,
                fetched_at,
                title,
                company,
                location,
                description_text,
                description_hash,
                description_similarity_to_previous,
                change_ratio,
                json.dumps(requirements_json) if requirements_json is not None else None,
                json.dumps(responsibilities_json) if responsibilities_json is not None else None,
                apply_url,
                json.dumps(extracted_keywords_json) if extracted_keywords_json is not None else None,
                raw_html_path,
                raw_text_path,
                raw_json_path,
            ),
        )
        if cursor.lastrowid:
            snapshot_id = int(cursor.lastrowid)
        else:
            row = self.connection.execute(
                """
                SELECT id FROM job_snapshots
                WHERE posting_id = ? AND description_hash = ?
                LIMIT 1
                """,
                (posting_id, description_hash),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert job snapshot")
            snapshot_id = int(row["id"])
        self.connection.commit()
        return snapshot_id

    def fetch_job_posting(self, posting_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM job_postings WHERE id = ?",
            (posting_id,),
        ).fetchone()

    def fetch_latest_snapshot(self, posting_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM job_snapshots
            WHERE posting_id = ?
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """,
            (posting_id,),
        ).fetchone()

    def update_job_posting_status(
        self,
        posting_id: int,
        status: str,
        *,
        needs_human_decision: int | None = None,
        decision_reason: str | None = None,
    ) -> None:
        now = utc_now()
        self.connection.execute(
            """
            UPDATE job_postings
            SET status = ?,
                needs_human_decision = COALESCE(?, needs_human_decision),
                decision_reason = COALESCE(?, decision_reason),
                updated_at = ?
            WHERE id = ?
            """,
            (status, needs_human_decision, decision_reason, now, posting_id),
        )
        self.connection.commit()

    def get_latest_snapshot_for_family(self, family_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT js.*
            FROM job_postings jp
            JOIN job_snapshots js ON js.posting_id = jp.id
            WHERE jp.family_id = ?
            ORDER BY js.fetched_at DESC, js.id DESC
            LIMIT 1
            """,
            (family_id,),
        ).fetchone()

    def family_has_source_job_id(self, family_id: int, source_job_id: str | None) -> bool:
        if not source_job_id:
            return False
        row = self.connection.execute(
            """
            SELECT 1
            FROM job_postings
            WHERE family_id = ? AND source_job_id = ?
            LIMIT 1
            """,
            (family_id, source_job_id),
        ).fetchone()
        return row is not None

    def family_has_normalized_url(self, family_id: int, normalized_url: str | None) -> bool:
        if not normalized_url:
            return False
        row = self.connection.execute(
            """
            SELECT 1
            FROM job_postings
            WHERE family_id = ? AND normalized_url = ?
            LIMIT 1
            """,
            (family_id, normalized_url),
        ).fetchone()
        return row is not None

    def fetch_families_for_company(self, company_id: int | None) -> list[sqlite3.Row]:
        if company_id is None:
            return []
        rows = self.connection.execute(
            """
            SELECT * FROM job_families
            WHERE company_id = ?
            ORDER BY last_seen_at DESC, id DESC
            """,
            (company_id,),
        ).fetchall()
        return list(rows)

    def get_family_by_key(self, family_key: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM job_families WHERE family_key = ?",
            (family_key,),
        ).fetchone()

    def fetch_family_by_id(self, family_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM job_families WHERE id = ?",
            (family_id,),
        ).fetchone()

    def create_family(
        self,
        *,
        company_id: int | None,
        canonical_company: str,
        canonical_title: str,
        canonical_location: str | None,
        family_key: str,
        seen_at: str | None = None,
    ) -> int:
        seen_at = seen_at or utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO job_families (
              canonical_company, canonical_title, canonical_location, family_key,
              created_at, updated_at, first_seen_at, last_seen_at, company_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_company,
                canonical_title,
                canonical_location,
                family_key,
                seen_at,
                seen_at,
                seen_at,
                seen_at,
                company_id,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_family_seen(self, family_id: int, seen_at: str | None = None) -> None:
        seen_at = seen_at or utc_now()
        self.connection.execute(
            "UPDATE job_families SET last_seen_at = ?, updated_at = ? WHERE id = ?",
            (seen_at, seen_at, family_id),
        )
        self.connection.commit()

    def update_family_canonical(
        self,
        family_id: int,
        *,
        canonical_company: str | None = None,
        canonical_title: str | None = None,
        canonical_location: str | None = None,
    ) -> None:
        now = utc_now()
        self.connection.execute(
            """
            UPDATE job_families
            SET canonical_company = COALESCE(?, canonical_company),
                canonical_title = COALESCE(?, canonical_title),
                canonical_location = COALESCE(?, canonical_location),
                updated_at = ?
            WHERE id = ?
            """,
            (canonical_company, canonical_title, canonical_location, now, family_id),
        )
        self.connection.commit()

    def attach_posting_to_family(self, posting_id: int, family_id: int) -> None:
        now = utc_now()
        self.connection.execute(
            "UPDATE job_postings SET family_id = ?, updated_at = ? WHERE id = ?",
            (family_id, now, posting_id),
        )
        self.connection.commit()

    def record_application_event(
        self,
        *,
        application_id: int | None,
        posting_id: int | None,
        event_type: str,
        message: str | None = None,
        data: dict[str, Any] | None = None,
        event_time: str | None = None,
    ) -> int:
        event_time = event_time or utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO application_events (
              application_id, posting_id, event_type, event_time, message, data_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (application_id, posting_id, event_type, event_time, message, json.dumps(data) if data else None),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_company_memory(
        self,
        *,
        company_id: int | None = None,
        company_name: str | None = None,
    ) -> sqlite3.Row | None:
        if company_id is not None:
            row = self.connection.execute(
                "SELECT * FROM company_memory WHERE company_id = ? LIMIT 1",
                (company_id,),
            ).fetchone()
            if row is not None:
                return row
        if company_name:
            normalized = normalize_text(company_name)
            rows = self.connection.execute(
                """
                SELECT * FROM company_memory
                ORDER BY updated_at DESC, id DESC
                """,
            ).fetchall()
            for row in rows:
                if normalize_text(str(row["company_name"])) == normalized:
                    return row
        return None

    def ensure_company_memory(self, company_id: int | None, company_name: str) -> int:
        existing = self.get_company_memory(company_id=company_id, company_name=company_name)
        now = utc_now()
        if existing is not None:
            memory_id = int(existing["id"])
            self.connection.execute(
                """
                UPDATE company_memory
                SET company_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (company_name, now, memory_id),
            )
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO company_memory (
                  company_id, company_name, updated_at
                ) VALUES (?, ?, ?)
                """,
                (company_id, company_name, now),
            )
            memory_id = int(cursor.lastrowid)
        self.connection.commit()
        return memory_id

    def update_company_memory(
        self,
        *,
        company_id: int | None = None,
        company_name: str | None = None,
        applications_total_delta: int = 0,
        positive_replies_total_delta: int = 0,
        auto_rejections_total_delta: int = 0,
        last_applied_at: str | None = None,
        last_positive_reply_at: str | None = None,
        notes: str | None = None,
    ) -> int:
        if company_id is None and company_name is None:
            raise ValueError("company_id or company_name is required")
        existing = self.get_company_memory(company_id=company_id, company_name=company_name)
        now = utc_now()
        if existing is None:
            memory_id = self.ensure_company_memory(company_id, company_name or "unknown")
            existing = self.connection.execute("SELECT * FROM company_memory WHERE id = ?", (memory_id,)).fetchone()
        if existing is None:
            raise RuntimeError("Failed to resolve company memory row")
        memory_id = int(existing["id"])
        new_company_name = company_name or str(existing["company_name"])
        self.connection.execute(
            """
            UPDATE company_memory
            SET company_name = ?,
                applications_total = COALESCE(applications_total, 0) + ?,
                positive_replies_total = COALESCE(positive_replies_total, 0) + ?,
                auto_rejections_total = COALESCE(auto_rejections_total, 0) + ?,
                last_applied_at = COALESCE(?, last_applied_at),
                last_positive_reply_at = COALESCE(?, last_positive_reply_at),
                notes = COALESCE(?, notes),
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_company_name,
                applications_total_delta,
                positive_replies_total_delta,
                auto_rejections_total_delta,
                last_applied_at,
                last_positive_reply_at,
                notes,
                now,
                memory_id,
            ),
        )
        self.connection.commit()
        return memory_id

    def list_previous_applications(
        self,
        *,
        company_id: int | None = None,
        family_id: int | None = None,
        posting_id: int | None = None,
        submitted_only: bool = False,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if company_id is not None:
            clauses.append("a.company_id = ?")
            params.append(company_id)
        if family_id is not None:
            clauses.append("a.family_id = ?")
            params.append(family_id)
        if posting_id is not None:
            clauses.append("a.posting_id = ?")
            params.append(posting_id)
        if submitted_only:
            clauses.append(
                "a.status IN ('submitted', 'submitted_verified', 'submitted_unverified', 'confirmation_received')"
            )
        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = self.connection.execute(
            f"""
            SELECT
              a.*,
              jp.source,
              jp.company AS posting_company,
              jp.title AS posting_title,
              jp.location AS posting_location,
              jp.url AS posting_url,
              jp.normalized_url,
              jp.source_job_id,
              jp.source_job_id AS previous_source_job_id,
              jp.family_id AS posting_family_id,
              (
                SELECT rv.resume_pdf_path
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_pdf_path,
              (
                SELECT rv.resume_json_path
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_json_path,
              (
                SELECT rv.resume_sha256
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_sha256
            FROM applications a
            JOIN job_postings jp ON jp.id = a.posting_id
            {where_sql}
            ORDER BY COALESCE(a.submitted_at, a.created_at) DESC, a.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return list(rows)

    def list_application_events(self, application_id: int | None = None, posting_id: int | None = None) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if application_id is not None:
            clauses.append("application_id = ?")
            params.append(application_id)
        if posting_id is not None:
            clauses.append("posting_id = ?")
            params.append(posting_id)
        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT * FROM application_events
            {where_sql}
            ORDER BY event_time DESC, id DESC
            """,
            params,
        ).fetchall()
        return list(rows)

    def list_daily_submitted_applications(self, run_date: str) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              a.id AS application_id,
              COALESCE(c.name, jp.company) AS company,
              jp.title,
              jp.source,
              a.status,
              a.submitted_at,
              a.application_url,
              a.error,
              jp.relevance_score,
              (
                SELECT rv.variant_name FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_variant,
              (
                SELECT rv.resume_pdf_path FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_pdf_path,
              (
                SELECT rv.resume_json_path FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_json_path,
              (
                SELECT rv.resume_sha256 FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS resume_sha256,
              (
                SELECT rv.tailoring_score FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS tailoring_confidence
            FROM applications a
            JOIN job_postings jp ON jp.id = a.posting_id
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE a.submitted_at IS NOT NULL
              AND date(a.submitted_at) = ?
              AND a.status IN ('submitted', 'submitted_verified', 'submitted_unverified', 'confirmation_received')
            ORDER BY a.submitted_at DESC, a.id DESC
            """,
            (run_date,),
        ).fetchall()
        return list(rows)

    def list_daily_positive_signals(self, run_date: str) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              em.id AS email_message_id,
              em.application_id,
              COALESCE(c.name, jp.company) AS company,
              jp.title,
              em.classification,
              em.subject,
              em.sender,
              em.received_at,
              em.body_path,
              em.snippet
            FROM email_messages em
            LEFT JOIN applications a ON a.id = em.application_id
            LEFT JOIN job_postings jp ON jp.id = a.posting_id
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE em.classification IN ('positive_reply', 'assessment_request', 'interview_request', 'scheduling')
              AND em.visible_to_user = 1
              AND (
                em.received_at IS NULL
                OR date(em.received_at) = ?
              )
            ORDER BY em.received_at DESC, em.id DESC
            """,
            (run_date,),
        ).fetchall()
        return list(rows)

    def list_daily_pending_decisions(self, run_date: str, *, window_days: int = 7) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              hd.id AS decision_id,
              COALESCE(c.name, jp.company) AS company,
              jp.title,
              jp.url AS job_url,
              hd.question,
              hd.recommendation,
              hd.user_decision,
              hd.related_application_id,
              hd.decided_at,
              a.submitted_at AS previous_application_submitted_at,
              (
                SELECT rv.resume_pdf_path
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS previous_resume_pdf_path,
              (
                SELECT rv.resume_json_path
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS previous_resume_json_path,
              (
                SELECT rv.resume_sha256
                FROM resume_variants rv
                WHERE rv.application_id = a.id
                ORDER BY rv.id DESC
                LIMIT 1
              ) AS previous_resume_sha256,
              a.application_url AS previous_application_url
            FROM human_decisions hd
            JOIN job_postings jp ON jp.id = hd.posting_id
            LEFT JOIN applications a ON a.id = hd.related_application_id
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE hd.user_decision IS NULL
              AND date(hd.created_at) >= date(?, ?)
            ORDER BY hd.created_at DESC, hd.id DESC
            """,
            (run_date, f"-{window_days} days"),
        ).fetchall()
        return list(rows)

    def list_daily_failures(self, run_date: str) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              a.id AS application_id,
              COALESCE(c.name, jp.company) AS company,
              jp.title,
              a.status,
              a.application_url,
              a.error,
              (
                SELECT ae.message
                FROM application_events ae
                WHERE ae.application_id = a.id
                  AND ae.event_type IN ('fetch_failed', 'validation_failed', 'tailor_failed', 'truth_guard_failed', 'pdf_render_failed', 'submit_failed', 'manual_checkpoint_required')
                ORDER BY ae.event_time DESC, ae.id DESC
                LIMIT 1
              ) AS message,
              (
                SELECT ae.event_type
                FROM application_events ae
                WHERE ae.application_id = a.id
                  AND ae.event_type IN ('fetch_failed', 'validation_failed', 'tailor_failed', 'truth_guard_failed', 'pdf_render_failed', 'submit_failed', 'manual_checkpoint_required')
                ORDER BY ae.event_time DESC, ae.id DESC
                LIMIT 1
              ) AS event_type
            FROM applications a
            JOIN job_postings jp ON jp.id = a.posting_id
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE (
              a.error IS NOT NULL
              OR a.status IN ('failed', 'needs_action', 'needs_manual_checkpoint', 'manual_checkpoint_required')
              OR EXISTS (
                SELECT 1
                FROM application_events ae
                WHERE ae.application_id = a.id
                  AND ae.event_type IN ('fetch_failed', 'validation_failed', 'tailor_failed', 'truth_guard_failed', 'pdf_render_failed', 'submit_failed', 'manual_checkpoint_required')
              )
            )
            AND (
              date(a.created_at) = ?
              OR date(a.updated_at) = ?
            )
            ORDER BY COALESCE(a.updated_at, a.created_at) DESC, a.id DESC
            """,
            (run_date, run_date),
        ).fetchall()
        return list(rows)

    def list_reapply_candidates(self) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              jp.*,
              jf.canonical_company,
              jf.canonical_title,
              jf.canonical_location
            FROM job_postings jp
            LEFT JOIN job_families jf ON jf.id = jp.family_id
            WHERE jp.family_id IS NOT NULL
              AND jp.status IN ('open', 'validated', 'packet_ready', 'reposted')
            ORDER BY jp.last_seen_at DESC, jp.id DESC
            """
        ).fetchall()
        return list(rows)

    def human_decision_exists(self, *, posting_id: int, related_application_id: int, decision_type: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM human_decisions
            WHERE posting_id = ?
              AND related_application_id = ?
              AND decision_type = ?
            LIMIT 1
            """,
            (posting_id, related_application_id, decision_type),
        ).fetchone()
        return row is not None

    def mark_resume_pdf_deleted(self, resume_variant_id: int, deleted_at: str | None = None) -> None:
        deleted_at = deleted_at or utc_now()
        self.connection.execute(
            """
            UPDATE resume_variants
            SET resume_pdf_path = NULL,
                resume_pdf_deleted_at = ?
            WHERE id = ?
            """,
            (deleted_at, resume_variant_id),
        )
        self.connection.commit()

    def insert_application(self, application: ApplicationInput) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO applications (
              posting_id, family_id, snapshot_id, company_id, status, submission_method, submitted_at,
              email_used, application_url, confirmation_type, confirmation_text, confirmation_url,
              confirmation_screenshot_path, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application.posting_id,
                application.family_id,
                application.snapshot_id,
                application.company_id,
                application.status,
                application.submission_method,
                application.submitted_at,
                application.email_used,
                application.application_url,
                application.confirmation_type,
                application.confirmation_text,
                application.confirmation_url,
                application.confirmation_screenshot_path,
                application.error,
                now,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def fetch_application(self, application_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    def update_application_status(self, application_id: int, status: str, **fields: Any) -> None:
        now = utc_now()
        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, now]
        allowed_fields = {
            "submission_method",
            "submitted_at",
            "email_used",
            "application_url",
            "confirmation_type",
            "confirmation_text",
            "confirmation_url",
            "confirmation_screenshot_path",
            "error",
            "family_id",
            "company_id",
            "snapshot_id",
        }
        for key, value in fields.items():
            if key not in allowed_fields:
                raise ValueError(f"Unsupported application field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(application_id)
        self.connection.execute(
            f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        self.connection.commit()

    def insert_resume_variant(self, variant: ResumeVariantInput) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO resume_variants (
              application_id, variant_name, base_resume_version, target_title, resume_json_path,
              resume_docx_path, resume_pdf_path, resume_text_path, resume_sha256, tailoring_model,
              tailoring_prompt_hash, truth_profile_hash, truth_guard_report_path, diff_summary_path,
              tailoring_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                variant.application_id,
                variant.variant_name,
                variant.base_resume_version,
                variant.target_title,
                variant.resume_json_path,
                variant.resume_docx_path,
                variant.resume_pdf_path,
                variant.resume_text_path,
                variant.resume_sha256,
                variant.tailoring_model,
                variant.tailoring_prompt_hash,
                variant.truth_profile_hash,
                variant.truth_guard_report_path,
                variant.diff_summary_path,
                variant.tailoring_score,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def fetch_latest_resume_variant(self, application_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM resume_variants
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

    def insert_submission_artifact(self, artifact: SubmissionArtifactInput) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO submission_artifacts (
              application_id, artifact_type, path, text_value, sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (artifact.application_id, artifact.artifact_type, artifact.path, artifact.text_value, artifact.sha256, now),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def insert_human_decision(self, decision: HumanDecisionInput) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO human_decisions (
              posting_id, related_application_id, decision_type, question, recommendation,
              user_decision, decided_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.posting_id,
                decision.related_application_id,
                decision.decision_type,
                decision.question,
                decision.recommendation,
                decision.user_decision,
                decision.decided_at,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def insert_email_message(self, message: EmailMessageInput) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT INTO email_messages (
              application_id, gmail_message_id, thread_id, classification, subject, sender,
              sender_domain, received_at, snippet, body_path, action_required, visible_to_user,
              created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.application_id,
                message.gmail_message_id,
                message.thread_id,
                message.classification,
                message.subject,
                message.sender,
                message.sender_domain,
                message.received_at,
                message.snippet,
                message.body_path,
                message.action_required,
                message.visible_to_user,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_pending_human_decisions(self) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT hd.*, jp.company, jp.title, jp.location, jp.source, jp.url, jp.normalized_url
            FROM human_decisions hd
            JOIN job_postings jp ON jp.id = hd.posting_id
            WHERE hd.user_decision IS NULL
            ORDER BY hd.created_at DESC, hd.id DESC
            """
        ).fetchall()
        return list(rows)

    def list_submission_artifacts(self, application_id: int) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT * FROM submission_artifacts
            WHERE application_id = ?
            ORDER BY id ASC
            """,
            (application_id,),
        ).fetchall()
        return list(rows)

    def application_has_positive_signal(self, application_id: int) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM email_messages
            WHERE application_id = ?
              AND classification IN ('positive_reply', 'assessment_request', 'interview_request', 'scheduling')
              AND visible_to_user = 1
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        return row is not None

    def list_resume_variants_for_retention(self, cutoff_date: str) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT
              rv.id AS resume_variant_id,
              rv.application_id,
              rv.resume_pdf_path,
              rv.resume_pdf_deleted_at,
              a.submitted_at,
              a.application_url,
              jp.company,
              jp.title
            FROM resume_variants rv
            JOIN applications a ON a.id = rv.application_id
            JOIN job_postings jp ON jp.id = a.posting_id
            WHERE rv.resume_pdf_path IS NOT NULL
              AND rv.resume_pdf_deleted_at IS NULL
              AND a.submitted_at IS NOT NULL
              AND date(a.submitted_at) < date(?)
            ORDER BY a.submitted_at ASC, rv.id ASC
            """,
            (cutoff_date,),
        ).fetchall()
        return list(rows)
