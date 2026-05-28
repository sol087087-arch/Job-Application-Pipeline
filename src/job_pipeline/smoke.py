from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Iterable

from job_pipeline.artifacts.writer import ArtifactWriter
from job_pipeline.cleanup.retention import cleanup_resume_pdfs
from job_pipeline.db.repository import (
    ApplicationInput,
    EmailMessageInput,
    JobPostingInput,
    Repository,
    ResumeVariantInput,
    SubmissionArtifactInput,
)
from job_pipeline.matching.family_linker import link_job_family
from job_pipeline.matching.apply_gate import evaluate_apply_eligibility
from job_pipeline.matching.reapply import sync_reapply_decision_queue
from job_pipeline.reports.daily import project_daily_report, render_daily_report_text


def _schema_path() -> Path:
    return Path(resources.files("job_pipeline.db").joinpath("schema.sql"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _iso_at(run_date: date, hour: int) -> str:
    return datetime(run_date.year, run_date.month, run_date.day, hour, 0, tzinfo=timezone.utc).isoformat()


def _write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    return path


def run_controlled_smoke(root: Path, run_date: date) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "jobs.sqlite"
    artifacts_root = root / "artifacts"
    writer = ArtifactWriter(artifacts_root)

    repository = Repository(db_path, _schema_path())
    try:
        company_id = repository.upsert_company("Example AI Labs", website="https://example.invalid")

        posting_id = repository.insert_job_posting(
            JobPostingInput(
                source="greenhouse",
                source_job_id="smoke-001",
                company="Example AI Labs",
                title="AI Model Quality Analyst",
                location="Remote",
                url="https://example.invalid/jobs/smoke-001",
                apply_url="https://example.invalid/jobs/smoke-001/apply",
                source_priority=10,
            ),
            company_id=company_id,
        )
        snapshot_id = repository.insert_job_snapshot(
            posting_id,
            title="AI Model Quality Analyst",
            company="Example AI Labs",
            location="Remote",
            description_text=(
                "Evaluate LLM behavior, prompt quality, refusal quality, and model output consistency. "
                "Document issues and improve AI quality workflows."
            ),
            extracted_keywords_json=["LLM evaluation", "prompt testing", "model quality"],
        )
        family = link_job_family(
            repository,
            posting_id=posting_id,
            company_id=company_id,
            company="Example AI Labs",
            title="AI Model Quality Analyst",
            location="Remote",
            description_text="Evaluate LLM behavior and model quality workflows.",
            source_job_id="smoke-001",
            normalized_url="https://example.invalid/jobs/smoke-001",
        )

        application_id = repository.insert_application(
            ApplicationInput(
                posting_id=posting_id,
                family_id=family.family_id,
                snapshot_id=snapshot_id,
                company_id=company_id,
                status="submitted_verified",
                submission_method="smoke",
                submitted_at=_iso_at(run_date, 9),
                email_used="candidate@example.invalid",
                application_url="https://example.invalid/jobs/smoke-001/apply",
                confirmation_type="page",
                confirmation_text="Application received.",
            )
        )

        paths = writer.ensure_application_tree(
            run_date=run_date,
            source="greenhouse",
            company_name="Example AI Labs",
            job_identifier="smoke-001",
            application_id=application_id,
        )
        writer.write_job_artifacts(
            paths,
            snapshot={"posting_id": posting_id, "snapshot_id": snapshot_id},
            clean_description="Evaluate LLM behavior and model quality workflows.",
            raw_job={"id": "smoke-001"},
        )
        resume_pdf = b"%PDF-1.4\n% smoke resume\n"
        resume_outputs = writer.write_resume_artifacts(
            paths,
            tailored_resume_json={"name": "Candidate", "target_title": "AI Model Quality Analyst"},
            tailored_resume_text="Candidate\nAI Model Quality Analyst\nLLM evaluation.",
            diff_summary="Smoke diff summary.",
            truth_guard={"status": "pass"},
            resume_pdf_bytes=resume_pdf,
        )
        submission_outputs = writer.write_submission_artifacts(
            paths,
            cover_note="Smoke cover note.",
            form_answers={"source": "Company careers site"},
            confirmation_text="Application received.",
            submit_result={"status": "submitted_verified"},
        )

        repository.insert_resume_variant(
            ResumeVariantInput(
                application_id=application_id,
                variant_name="smoke",
                base_resume_version="smoke-base",
                target_title="AI Model Quality Analyst",
                resume_json_path=str(resume_outputs["tailored_resume_json"]),
                resume_pdf_path=str(resume_outputs["tailored_resume_pdf"]),
                resume_text_path=str(resume_outputs["tailored_resume_text"]),
                resume_sha256=_sha256_bytes(resume_pdf),
                tailoring_model="smoke-tailor",
                tailoring_prompt_hash="smoke-prompt",
                truth_profile_hash="smoke-profile",
                truth_guard_report_path=str(resume_outputs["truth_guard"]),
                diff_summary_path=str(resume_outputs["diff_summary"]),
                tailoring_score=0.91,
            )
        )
        repository.insert_submission_artifact(
            SubmissionArtifactInput(
                application_id=application_id,
                artifact_type="confirmation",
                path=str(submission_outputs["confirmation"]),
            )
        )

        repository.insert_email_message(
            EmailMessageInput(
                application_id=application_id,
                gmail_message_id="smoke-positive",
                classification="assessment_request",
                subject="Next step: assessment",
                sender="recruiting@example.invalid",
                sender_domain="example.invalid",
                received_at=_iso_at(run_date, 10),
                snippet="Please complete the assessment.",
                visible_to_user=1,
                action_required=1,
            )
        )
        repository.insert_email_message(
            EmailMessageInput(
                application_id=application_id,
                gmail_message_id="smoke-rejection",
                classification="auto_rejection",
                subject="Rejected smoke message should stay hidden",
                sender="noreply@example.invalid",
                sender_domain="example.invalid",
                received_at=_iso_at(run_date, 11),
                snippet="We moved forward with other candidates.",
                visible_to_user=0,
            )
        )

        repost_id = repository.insert_job_posting(
            JobPostingInput(
                source="greenhouse",
                source_job_id="smoke-002",
                company="Example AI Labs",
                title="AI Model Quality Analyst",
                location="Remote",
                url="https://example.invalid/jobs/smoke-002",
                apply_url="https://example.invalid/jobs/smoke-002/apply",
                source_priority=10,
            ),
            company_id=company_id,
        )
        repository.insert_job_snapshot(
            repost_id,
            title="AI Model Quality Analyst",
            company="Example AI Labs",
            location="Remote",
            description_text="Evaluate LLM behavior, prompt quality, and model output consistency.",
        )
        link_job_family(
            repository,
            posting_id=repost_id,
            company_id=company_id,
            company="Example AI Labs",
            title="AI Model Quality Analyst",
            location="Remote",
            description_text="Evaluate LLM behavior, prompt quality, and model output consistency.",
            source_job_id="smoke-002",
            normalized_url="https://example.invalid/jobs/smoke-002",
        )
        apply_eligibility = evaluate_apply_eligibility(repository, posting_id=repost_id, run_date=run_date)
        created_decisions = sync_reapply_decision_queue(repository, run_date)

        checkpoint_posting_id = repository.insert_job_posting(
            JobPostingInput(
                source="lever",
                source_job_id="smoke-checkpoint",
                company="Checkpoint Co",
                title="Prompt Evaluation Specialist",
                location="Remote",
                url="https://checkpoint.invalid/jobs/1",
                apply_url="https://checkpoint.invalid/jobs/1/apply",
                source_priority=10,
            )
        )
        checkpoint_snapshot_id = repository.insert_job_snapshot(
            checkpoint_posting_id,
            title="Prompt Evaluation Specialist",
            company="Checkpoint Co",
            location="Remote",
            description_text="Prompt evaluation role with CAPTCHA checkpoint.",
        )
        checkpoint_app_id = repository.insert_application(
            ApplicationInput(
                posting_id=checkpoint_posting_id,
                snapshot_id=checkpoint_snapshot_id,
                status="manual_checkpoint_required",
                application_url="https://checkpoint.invalid/jobs/1/apply",
                error="CAPTCHA required",
            )
        )
        repository.record_application_event(
            application_id=checkpoint_app_id,
            posting_id=checkpoint_posting_id,
            event_type="manual_checkpoint_required",
            message="CAPTCHA required. Open application URL to continue.",
            data={"url": "https://checkpoint.invalid/jobs/1/apply"},
        )

        old_date = run_date - timedelta(days=45)
        old_posting_id = repository.insert_job_posting(
            JobPostingInput(
                source="greenhouse",
                source_job_id="smoke-old",
                company="Old PDF Co",
                title="Data Quality Analyst",
                location="Remote",
                url="https://old.invalid/jobs/1",
            )
        )
        old_snapshot_id = repository.insert_job_snapshot(
            old_posting_id,
            title="Data Quality Analyst",
            company="Old PDF Co",
            description_text="Old PDF cleanup test.",
            location="Remote",
        )
        old_app_id = repository.insert_application(
            ApplicationInput(
                posting_id=old_posting_id,
                snapshot_id=old_snapshot_id,
                status="submitted_verified",
                submitted_at=_iso_at(old_date, 9),
            )
        )
        old_pdf_path = artifacts_root / "old" / "tailored_resume.pdf"
        old_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        old_pdf_bytes = b"%PDF-1.4\n% old smoke resume\n"
        old_pdf_path.write_bytes(old_pdf_bytes)
        repository.insert_resume_variant(
            ResumeVariantInput(
                application_id=old_app_id,
                variant_name="old-smoke",
                base_resume_version="smoke-base",
                resume_json_path=str(_write_json(artifacts_root / "old" / "tailored_resume.json", {"old": True})),
                resume_pdf_path=str(old_pdf_path),
                resume_sha256=_sha256_bytes(old_pdf_bytes),
            )
        )

        report = project_daily_report(repository, run_date)
        report_text = render_daily_report_text(report)
        cleanup = cleanup_resume_pdfs(
            repository,
            artifacts_dir=artifacts_root,
            keep_days_without_reply=30,
            run_date=run_date,
        )

        assert "Submitted:" in report_text
        assert "Example AI Labs" in report_text
        assert "assessment_request" in report_text
        assert "Rejected smoke message should stay hidden" not in report_text
        assert "We moved forward with other candidates" not in report_text
        assert apply_eligibility.action == "blocked_recent_duplicate"
        assert apply_eligibility.can_submit is False
        assert created_decisions == 0
        assert report.failures
        assert cleanup.deleted == 1
        assert not old_pdf_path.exists()

        report_path = root / "smoke_report.txt"
        summary_path = root / "smoke_summary.json"
        report_path.write_text(report_text, encoding="utf-8")
        summary = {
            "root": str(root),
            "db_path": str(db_path),
            "report_path": str(report_path),
            "submitted_count": len(report.submitted),
            "positive_signal_count": len(report.positive_signals),
            "needs_decision_count": len(report.needs_decision),
            "failure_count": len(report.failures),
            "created_reapply_decisions": created_decisions,
            "recent_duplicate_gate_action": apply_eligibility.action,
            "retention_deleted_count": cleanup.deleted,
            "retention_kept_positive_reply_count": cleanup.kept_positive_reply,
            "status": "pass",
        }
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        return summary
    finally:
        repository.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-pipeline-smoke")
    parser.add_argument("--root", default=None, help="Smoke output root. Defaults to a temp dir.")
    parser.add_argument("--date", dest="run_date", default=None, help="YYYY-MM-DD, defaults to today.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_date = date.fromisoformat(args.run_date) if args.run_date else date.today()
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="job_pipeline_smoke_"))
    summary = run_controlled_smoke(root.resolve(), run_date)
    print(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
