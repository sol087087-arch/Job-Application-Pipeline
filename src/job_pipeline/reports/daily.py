from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from job_pipeline.db.repository import Repository


def _display_path(value: str | None) -> str:
    return value or ""


def _format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


@dataclass(frozen=True)
class DailySubmittedItem:
    application_id: int
    company: str
    title: str
    source: str
    status: str
    submitted_at: str | None
    resume_variant: str | None
    resume_pdf_path: str | None
    resume_json_path: str | None
    resume_sha256: str | None
    application_url: str | None
    score: float | None
    tailoring_confidence: float | None


@dataclass(frozen=True)
class DailyPositiveSignalItem:
    email_message_id: int
    application_id: int | None
    company: str
    title: str
    classification: str
    subject: str | None
    sender: str | None
    received_at: str | None
    body_path: str | None
    snippet: str | None


@dataclass(frozen=True)
class DailyDecisionItem:
    decision_id: int
    company: str
    title: str
    job_url: str | None
    question: str
    recommendation: str | None
    user_decision: str | None
    related_application_id: int | None
    decided_at: str | None
    previous_application_submitted_at: str | None = None
    previous_resume_pdf_path: str | None = None
    previous_resume_json_path: str | None = None
    previous_resume_sha256: str | None = None
    previous_application_url: str | None = None


@dataclass(frozen=True)
class DailyFailureItem:
    application_id: int | None
    company: str
    title: str
    status: str
    application_url: str | None
    message: str | None
    error: str | None
    event_type: str | None = None


@dataclass(frozen=True)
class DailyReport:
    run_date: date
    submitted: list[DailySubmittedItem] = field(default_factory=list)
    positive_signals: list[DailyPositiveSignalItem] = field(default_factory=list)
    needs_decision: list[DailyDecisionItem] = field(default_factory=list)
    failures: list[DailyFailureItem] = field(default_factory=list)


def project_daily_report(repository: Repository, run_date: date) -> DailyReport:
    report = DailyReport(run_date=run_date)
    run_date_str = run_date.isoformat()
    submitted_rows = repository.list_daily_submitted_applications(run_date_str)
    for row in submitted_rows:
        report.submitted.append(
            DailySubmittedItem(
                application_id=int(row["application_id"]),
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                source=str(row["source"] or ""),
                status=str(row["status"] or ""),
                submitted_at=row["submitted_at"],
                resume_variant=row["resume_variant"],
                resume_pdf_path=row["resume_pdf_path"],
                resume_json_path=row["resume_json_path"],
                resume_sha256=row["resume_sha256"],
                application_url=row["application_url"],
                score=row["relevance_score"],
                tailoring_confidence=row["tailoring_confidence"],
            )
        )

    positive_rows = repository.list_daily_positive_signals(run_date_str)
    for row in positive_rows:
        report.positive_signals.append(
            DailyPositiveSignalItem(
                email_message_id=int(row["email_message_id"]),
                application_id=row["application_id"],
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                classification=str(row["classification"] or ""),
                subject=row["subject"],
                sender=row["sender"],
                received_at=row["received_at"],
                body_path=row["body_path"],
                snippet=row["snippet"],
            )
        )

    decision_rows = repository.list_daily_pending_decisions(run_date_str)
    for row in decision_rows:
        report.needs_decision.append(
            DailyDecisionItem(
                decision_id=int(row["decision_id"]),
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                job_url=row["job_url"],
                question=str(row["question"] or ""),
                recommendation=row["recommendation"],
                user_decision=row["user_decision"],
                related_application_id=row["related_application_id"],
                decided_at=row["decided_at"],
                previous_application_submitted_at=row["previous_application_submitted_at"],
                previous_resume_pdf_path=row["previous_resume_pdf_path"],
                previous_resume_json_path=row["previous_resume_json_path"],
                previous_resume_sha256=row["previous_resume_sha256"],
                previous_application_url=row["previous_application_url"],
            )
        )

    failure_rows = repository.list_daily_failures(run_date_str)
    for row in failure_rows:
        report.failures.append(
            DailyFailureItem(
                application_id=row["application_id"],
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                status=str(row["status"] or ""),
                application_url=row["application_url"],
                message=row["message"],
                error=row["error"],
                event_type=row["event_type"],
            )
        )

    return report


def render_daily_report_text(report: DailyReport) -> str:
    lines: list[str] = [f"Daily run report - {report.run_date.isoformat()}", ""]

    lines.append("Submitted:")
    if report.submitted:
        for item in report.submitted:
            lines.extend(
                [
                    f"- {item.company} | {item.title}",
                    f"  source: {item.source}",
                    f"  status: {item.status}",
                    f"  resume variant: {item.resume_variant or 'n/a'}",
                    f"  resume pdf: {_display_path(item.resume_pdf_path) or 'n/a'}",
                    f"  resume json: {_display_path(item.resume_json_path) or 'n/a'}",
                    f"  score: {_format_number(item.score) or 'n/a'}",
                    f"  tailoring confidence: {_format_number(item.tailoring_confidence) or 'n/a'}",
                    f"  application url: {item.application_url or 'n/a'}",
                ]
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Needs decision:")
    if report.needs_decision:
        for item in report.needs_decision:
            recommendation = item.recommendation or "n/a"
            decided = item.user_decision or "pending"
            lines.extend(
                [
                    f"- {item.company} | {item.title}",
                    f"  question: {item.question}",
                    f"  recommended: {recommendation}",
                    f"  decision: {decided}",
                    f"  previous application submitted at: {item.previous_application_submitted_at or 'n/a'}",
                    f"  previous resume pdf: {item.previous_resume_pdf_path or 'n/a'}",
                    f"  previous resume json: {item.previous_resume_json_path or 'n/a'}",
                    f"  previous application url: {item.previous_application_url or 'n/a'}",
                    f"  job url: {item.job_url or 'n/a'}",
                ]
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Positive signals:")
    if report.positive_signals:
        for item in report.positive_signals:
            lines.extend(
                [
                    f"- {item.company} | {item.classification}",
                    f"  title: {item.title or 'n/a'}",
                    f"  subject: {item.subject or 'n/a'}",
                    f"  sender: {item.sender or 'n/a'}",
                    f"  received at: {item.received_at or 'n/a'}",
                    f"  body: {item.body_path or 'n/a'}",
                ]
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Failed / debug:")
    if report.failures:
        for item in report.failures:
            detail = item.message or item.error or item.event_type or "unknown failure"
            lines.extend(
                [
                    f"- {item.company} | {item.title}",
                    f"  status: {item.status}",
                    f"  application url: {item.application_url or 'n/a'}",
                    f"  detail: {detail}",
                ]
            )
    else:
        lines.append("- none")

    return "\n".join(lines)
