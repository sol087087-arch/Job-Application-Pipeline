PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  website TEXT,
  greenhouse_token TEXT,
  lever_token TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_normalized_name
ON companies(normalized_name);

CREATE TABLE IF NOT EXISTS job_families (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_company TEXT NOT NULL,
  canonical_title TEXT NOT NULL,
  canonical_location TEXT,
  family_key TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  company_id INTEGER,
  FOREIGN KEY(company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS job_postings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER,
  company_id INTEGER,
  source TEXT NOT NULL,
  source_job_id TEXT,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  language TEXT DEFAULT 'en',
  url TEXT NOT NULL,
  normalized_url TEXT NOT NULL,
  apply_url TEXT,
  source_priority INTEGER DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'open',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  closed_seen_at TEXT,
  scrape_quality REAL DEFAULT 0,
  relevance_score REAL DEFAULT 0,
  dedupe_confidence REAL DEFAULT 0,
  repost_of_application_id INTEGER,
  needs_human_decision INTEGER DEFAULT 0,
  decision_reason TEXT,
  raw_json_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(family_id) REFERENCES job_families(id),
  FOREIGN KEY(company_id) REFERENCES companies(id),
  FOREIGN KEY(repost_of_application_id) REFERENCES applications(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_source_job
ON job_postings(source, source_job_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_url
ON job_postings(normalized_url);

CREATE INDEX IF NOT EXISTS idx_job_postings_family_id
ON job_postings(family_id);

CREATE TABLE IF NOT EXISTS job_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id INTEGER NOT NULL,
  fetched_at TEXT NOT NULL,
  title TEXT NOT NULL,
  company TEXT NOT NULL,
  location TEXT,
  description_text TEXT NOT NULL,
  description_hash TEXT NOT NULL,
  description_similarity_to_previous REAL,
  change_ratio REAL,
  requirements_json TEXT,
  responsibilities_json TEXT,
  apply_url TEXT,
  extracted_keywords_json TEXT,
  raw_html_path TEXT,
  raw_text_path TEXT,
  raw_json_path TEXT,
  FOREIGN KEY(posting_id) REFERENCES job_postings(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_snapshots_posting_hash
ON job_snapshots(posting_id, description_hash);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id INTEGER NOT NULL,
  family_id INTEGER,
  snapshot_id INTEGER NOT NULL,
  company_id INTEGER,
  status TEXT NOT NULL DEFAULT 'created',
  submission_method TEXT,
  submitted_at TEXT,
  email_used TEXT,
  application_url TEXT,
  confirmation_type TEXT,
  confirmation_text TEXT,
  confirmation_url TEXT,
  confirmation_screenshot_path TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(posting_id) REFERENCES job_postings(id),
  FOREIGN KEY(family_id) REFERENCES job_families(id),
  FOREIGN KEY(snapshot_id) REFERENCES job_snapshots(id),
  FOREIGN KEY(company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_applications_status
ON applications(status);

CREATE INDEX IF NOT EXISTS idx_applications_submitted_at
ON applications(submitted_at);

CREATE INDEX IF NOT EXISTS idx_applications_company_id
ON applications(company_id);

CREATE TABLE IF NOT EXISTS resume_variants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER NOT NULL,
  variant_name TEXT NOT NULL,
  base_resume_version TEXT NOT NULL,
  target_title TEXT,
  resume_json_path TEXT NOT NULL,
  resume_docx_path TEXT,
  resume_pdf_path TEXT,
  resume_pdf_deleted_at TEXT,
  resume_text_path TEXT,
  resume_sha256 TEXT NOT NULL,
  tailoring_model TEXT,
  tailoring_prompt_hash TEXT,
  truth_profile_hash TEXT,
  truth_guard_report_path TEXT,
  diff_summary_path TEXT,
  tailoring_score REAL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS submission_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER NOT NULL,
  artifact_type TEXT NOT NULL,
  path TEXT,
  text_value TEXT,
  sha256 TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS application_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER,
  posting_id INTEGER,
  event_type TEXT NOT NULL,
  event_time TEXT NOT NULL,
  message TEXT,
  data_json TEXT,
  FOREIGN KEY(application_id) REFERENCES applications(id),
  FOREIGN KEY(posting_id) REFERENCES job_postings(id)
);

CREATE INDEX IF NOT EXISTS idx_application_events_application_id
ON application_events(application_id);

CREATE TABLE IF NOT EXISTS email_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER,
  gmail_message_id TEXT UNIQUE,
  thread_id TEXT,
  classification TEXT NOT NULL,
  subject TEXT,
  sender TEXT,
  sender_domain TEXT,
  received_at TEXT,
  snippet TEXT,
  body_path TEXT,
  action_required INTEGER DEFAULT 0,
  visible_to_user INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_classification
ON email_messages(classification);

CREATE TABLE IF NOT EXISTS human_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id INTEGER NOT NULL,
  related_application_id INTEGER,
  decision_type TEXT NOT NULL,
  question TEXT NOT NULL,
  recommendation TEXT,
  user_decision TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(posting_id) REFERENCES job_postings(id),
  FOREIGN KEY(related_application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS company_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER,
  company_name TEXT NOT NULL,
  applications_total INTEGER DEFAULT 0,
  positive_replies_total INTEGER DEFAULT 0,
  auto_rejections_total INTEGER DEFAULT 0,
  last_applied_at TEXT,
  last_positive_reply_at TEXT,
  notes TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(company_id) REFERENCES companies(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_memory_company_id
ON company_memory(company_id);
