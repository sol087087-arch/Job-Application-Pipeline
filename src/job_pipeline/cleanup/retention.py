from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from job_pipeline.db.repository import Repository


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_delete_file(path: Path, artifacts_root: Path) -> bool:
    try:
        resolved_path = path.resolve(strict=False)
        resolved_root = artifacts_root.resolve(strict=True)
    except FileNotFoundError:
        return False
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return False
    if resolved_path.exists() and resolved_path.is_file():
        resolved_path.unlink()
        return True
    return False


def _resolve_pdf_path(path_value: str, artifacts_root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path

    cwd_candidate = path.resolve(strict=False)
    if cwd_candidate.exists():
        return cwd_candidate

    root_candidate = (artifacts_root / path).resolve(strict=False)
    if root_candidate.exists():
        return root_candidate

    return root_candidate


@dataclass(frozen=True)
class RetentionCleanupItem:
    resume_variant_id: int
    application_id: int
    company: str
    title: str
    submitted_at: str | None
    pdf_path: str
    deleted: bool
    reason: str


@dataclass
class RetentionCleanupResult:
    cutoff_date: date
    inspected: int = 0
    deleted: int = 0
    kept_positive_reply: int = 0
    missing_files: int = 0
    skipped_outside_root: int = 0
    items: list[RetentionCleanupItem] = field(default_factory=list)


def cleanup_resume_pdfs(
    repository: Repository,
    *,
    artifacts_dir: str | Path,
    keep_days_without_reply: int = 30,
    run_date: date | None = None,
) -> RetentionCleanupResult:
    run_date = run_date or date.today()
    cutoff_date = run_date - timedelta(days=keep_days_without_reply)
    artifacts_root = Path(artifacts_dir)
    result = RetentionCleanupResult(cutoff_date=cutoff_date)

    for row in repository.list_resume_variants_for_retention(cutoff_date.isoformat()):
        result.inspected += 1
        pdf_path_value = str(row["resume_pdf_path"] or "")
        if not pdf_path_value:
            result.items.append(
                RetentionCleanupItem(
                    resume_variant_id=int(row["resume_variant_id"]),
                    application_id=int(row["application_id"]),
                    company=str(row["company"] or ""),
                    title=str(row["title"] or ""),
                    submitted_at=row["submitted_at"],
                    pdf_path="",
                    deleted=False,
                    reason="missing path",
                )
            )
            result.missing_files += 1
            continue

        pdf_path = _resolve_pdf_path(pdf_path_value, artifacts_root)

        if repository.application_has_positive_signal(int(row["application_id"])):
            result.kept_positive_reply += 1
            result.items.append(
                RetentionCleanupItem(
                    resume_variant_id=int(row["resume_variant_id"]),
                    application_id=int(row["application_id"]),
                    company=str(row["company"] or ""),
                    title=str(row["title"] or ""),
                    submitted_at=row["submitted_at"],
                    pdf_path=str(pdf_path),
                    deleted=False,
                    reason="kept because positive reply exists",
                )
            )
            continue

        if not _safe_delete_file(pdf_path, artifacts_root):
            if pdf_path.exists():
                try:
                    pdf_path.resolve(strict=False).relative_to(artifacts_root.resolve(strict=True))
                    reason = "file could not be deleted"
                except ValueError:
                    result.skipped_outside_root += 1
                    reason = "skipped outside artifacts root"
            else:
                result.missing_files += 1
                reason = "file already missing"
            result.items.append(
                RetentionCleanupItem(
                    resume_variant_id=int(row["resume_variant_id"]),
                    application_id=int(row["application_id"]),
                    company=str(row["company"] or ""),
                    title=str(row["title"] or ""),
                    submitted_at=row["submitted_at"],
                    pdf_path=str(pdf_path),
                    deleted=False,
                    reason=reason,
                )
            )
            continue

        repository.mark_resume_pdf_deleted(int(row["resume_variant_id"]), utc_now())
        result.deleted += 1
        result.items.append(
            RetentionCleanupItem(
                resume_variant_id=int(row["resume_variant_id"]),
                application_id=int(row["application_id"]),
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                submitted_at=row["submitted_at"],
                pdf_path=str(pdf_path),
                deleted=True,
                reason="deleted after retention window",
            )
        )

    return result


def render_retention_cleanup_text(result: RetentionCleanupResult) -> str:
    lines = [
        f"Retention cleanup - {datetime.now(timezone.utc).date().isoformat()}",
        f"Cutoff date: {result.cutoff_date.isoformat()}",
        f"Inspected: {result.inspected}",
        f"Deleted PDFs: {result.deleted}",
        f"Kept due to positive reply: {result.kept_positive_reply}",
        f"Missing files: {result.missing_files}",
        f"Skipped outside root: {result.skipped_outside_root}",
        "",
    ]
    for item in result.items:
        status = "deleted" if item.deleted else "kept"
        lines.extend(
            [
                f"- {item.company} | {item.title}",
                f"  application id: {item.application_id}",
                f"  resume variant id: {item.resume_variant_id}",
                f"  submitted at: {item.submitted_at or 'n/a'}",
                f"  pdf: {item.pdf_path or 'n/a'}",
                f"  status: {status}",
                f"  reason: {item.reason}",
            ]
        )
    if not result.items:
        lines.append("- none")
    return "\n".join(lines)
