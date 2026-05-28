from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Iterable

from job_pipeline.cleanup.retention import cleanup_resume_pdfs, render_retention_cleanup_text
from job_pipeline.db.repository import Repository
from job_pipeline.matching.reapply import sync_reapply_decision_queue
from job_pipeline.reports.daily import DailyReport, project_daily_report, render_daily_report_text
from job_pipeline.telegram import load_telegram_config_from_env, send_telegram_message


def _default_db_path() -> Path:
    return Path(os.environ.get("JOB_PIPELINE_DB_PATH", "data/jobs.sqlite"))


def _default_artifacts_dir() -> Path:
    return Path(os.environ.get("JOB_PIPELINE_ARTIFACTS_DIR", "artifacts"))


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from exc


def _report_output_dir(artifacts_dir: Path, run_date: date) -> Path:
    return artifacts_dir / "reports" / "daily" / run_date.isoformat()


def _retention_output_dir(artifacts_dir: Path, run_date: date) -> Path:
    return artifacts_dir / "reports" / "retention" / run_date.isoformat()


@contextmanager
def _schema_path() -> Path:
    with resources.as_file(resources.files("job_pipeline.db").joinpath("schema.sql")) as schema_path:
        yield Path(schema_path)


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _write_report_outputs(report_dir: Path, filename_prefix: str, report: DailyReport) -> tuple[Path, Path]:
    report_text = render_daily_report_text(report)
    report_json = asdict(report)

    text_path = report_dir / f"{filename_prefix}.txt"
    json_path = report_dir / f"{filename_prefix}.json"
    text_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(json.dumps(report_json, indent=2, ensure_ascii=True, default=_json_default), encoding="utf-8")
    return text_path, json_path


def _send_report_to_telegram(report_text: str, text_path: Path, json_path: Path) -> None:
    telegram_config = load_telegram_config_from_env()
    if telegram_config is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set to send Telegram reports")
    telegram_message = "\n".join(
        [
            report_text,
            "",
            "Report files:",
            f"- text: {text_path}",
            f"- json: {json_path}",
        ]
    )
    send_telegram_message(telegram_config, telegram_message)


def _best_effort_send_report_to_telegram(report_text: str, text_path: Path, json_path: Path) -> None:
    try:
        _send_report_to_telegram(report_text, text_path, json_path)
    except RuntimeError as exc:
        print(f"Telegram delivery failed: {exc}", file=sys.stderr)


def run_report(
    *,
    db_path: Path,
    artifacts_dir: Path,
    run_date: date,
    send_telegram_report: bool = False,
) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_dir = _report_output_dir(artifacts_dir, run_date)
    report_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _schema_path() as schema_path:
        repository = Repository(db_path, schema_path)
        try:
            report = project_daily_report(repository, run_date)
        finally:
            repository.close()

    text_path, json_path = _write_report_outputs(report_dir, "report", report)

    if send_telegram_report:
        _best_effort_send_report_to_telegram(render_daily_report_text(report), text_path, json_path)

    return text_path


def run_daily(
    *,
    db_path: Path,
    artifacts_dir: Path,
    run_date: date,
    send_telegram_report: bool = False,
) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_dir = _report_output_dir(artifacts_dir, run_date)
    report_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _schema_path() as schema_path:
        repository = Repository(db_path, schema_path)
        try:
            sync_reapply_decision_queue(repository, run_date)
            report = project_daily_report(repository, run_date)
        finally:
            repository.close()

    text_path, json_path = _write_report_outputs(report_dir, "report", report)

    if send_telegram_report:
        _best_effort_send_report_to_telegram(render_daily_report_text(report), text_path, json_path)

    return text_path


def run_retention_cleanup(
    *,
    db_path: Path,
    artifacts_dir: Path,
    run_date: date,
    keep_days_without_reply: int = 30,
) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_dir = _retention_output_dir(artifacts_dir, run_date)
    report_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _schema_path() as schema_path:
        repository = Repository(db_path, schema_path)
        try:
            result = cleanup_resume_pdfs(
                repository,
                artifacts_dir=artifacts_dir,
                keep_days_without_reply=keep_days_without_reply,
                run_date=run_date,
            )
        finally:
            repository.close()

    report_text = render_retention_cleanup_text(result)
    report_json = asdict(result)

    text_path = report_dir / "cleanup.txt"
    json_path = report_dir / "cleanup.json"
    text_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(json.dumps(report_json, indent=2, ensure_ascii=True, default=_json_default), encoding="utf-8")
    return text_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="Render the daily report from SQLite")
    report_parser.add_argument("--date", dest="run_date", help="ISO date, defaults to today", default=None)
    report_parser.add_argument("--db-path", dest="db_path", default=None)
    report_parser.add_argument("--artifacts-dir", dest="artifacts_dir", default=None)
    report_parser.add_argument("--telegram", action="store_true", help="Send the report to Telegram")

    run_parser = subparsers.add_parser("run", help="Run the daily cycle")
    run_subparsers = run_parser.add_subparsers(dest="run_command", required=True)
    daily_parser = run_subparsers.add_parser("daily", help="Render and send the daily report")
    daily_parser.add_argument("--date", dest="run_date", help="ISO date, defaults to today", default=None)
    daily_parser.add_argument("--db-path", dest="db_path", default=None)
    daily_parser.add_argument("--artifacts-dir", dest="artifacts_dir", default=None)
    daily_parser.add_argument("--telegram", action="store_true", help="Send the report to Telegram")

    cleanup_parser = subparsers.add_parser("cleanup", help="Run cleanup and retention tasks")
    cleanup_subparsers = cleanup_parser.add_subparsers(dest="cleanup_command", required=True)
    retention_parser = cleanup_subparsers.add_parser("retention", help="Delete old PDFs and retain JSON artifacts")
    retention_parser.add_argument("--date", dest="run_date", help="ISO date, defaults to today", default=None)
    retention_parser.add_argument("--db-path", dest="db_path", default=None)
    retention_parser.add_argument("--artifacts-dir", dest="artifacts_dir", default=None)
    retention_parser.add_argument("--keep-days", dest="keep_days", type=int, default=30)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "report":
        db_path = Path(args.db_path) if args.db_path else _default_db_path()
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else _default_artifacts_dir()
        try:
            run_date = _parse_date(args.run_date)
        except ValueError as exc:
            parser.error(str(exc))
        report_path = run_report(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            run_date=run_date,
            send_telegram_report=bool(args.telegram),
        )
        print(report_path)
        return 0

    if args.command == "run" and args.run_command == "daily":
        db_path = Path(args.db_path) if args.db_path else _default_db_path()
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else _default_artifacts_dir()
        try:
            run_date = _parse_date(args.run_date)
        except ValueError as exc:
            parser.error(str(exc))
        report_path = run_daily(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            run_date=run_date,
            send_telegram_report=bool(args.telegram),
        )
        print(report_path)
        return 0

    if args.command == "cleanup" and args.cleanup_command == "retention":
        db_path = Path(args.db_path) if args.db_path else _default_db_path()
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else _default_artifacts_dir()
        try:
            run_date = _parse_date(args.run_date)
        except ValueError as exc:
            parser.error(str(exc))
        cleanup_path = run_retention_cleanup(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            run_date=run_date,
            keep_days_without_reply=int(args.keep_days),
        )
        print(cleanup_path)
        return 0

    raise RuntimeError("Unsupported command")
