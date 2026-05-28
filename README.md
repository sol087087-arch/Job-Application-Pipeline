# Job Application Pipeline

A local-first, scheduled batch pipeline for job discovery, resume tailoring, application submission, and rejection filtering.

---

## Why this exists

Modern hiring is already automated on the employer side. Job descriptions are parsed, resumes are ranked by ATS, and rejection emails are templated. Candidates routinely never interact with a human until they clear several automated layers.

This project responds to that reality:

- Jobs are fetched, validated, and deduplicated automatically
- Resumes are tailored per application from a structured truth profile — no manual rewriting
- Every submission is stored with full provenance
- Email is monitored; automated rejection noise is hidden
- Human attention is reserved for human signal: interview requests, assessments, recruiter replies

**What this is not:**

- Not a chatbot
- Not a LinkedIn bot
- Not a CAPTCHA bypass tool
- Not a fake-identity or credential-evasion system

---

## Core pipeline flow

```
Fetch jobs
  → Validate job postings
  → Snapshot descriptions
  → Link duplicates / reposts (job families)
  → Choose canonical application source
  → Score and rank candidates
  → Tailor resume from truth profile
  → Run truth guard
  → Render PDF
  → Submit application
  → Store artifacts + provenance record
  → Monitor email
  → Quarantine rejections
  → Surface positive signals only
  → Generate daily report
```

---

## What the pipeline optimises for

| Priority | Notes |
|---|---|
| High recall job discovery | Cast wide, filter later |
| Broad application coverage | Volume with integrity |
| Strict provenance | Know exactly what was sent |
| Resume version tracking | Every PDF stored |
| Reproducibility | Same inputs → same output |
| Low manual effort | Batch daily, not continuous |
| Local data ownership | SQLite, no cloud required |
| Low LLM cost | Deterministic steps first, LLM last |
| Small readable modules | No file over 300 lines |

**Not optimised for:**

- Beautiful UI (Phase 5)
- Perfect semantic job matching
- Hand-polished cover letters
- Heavy cloud infrastructure
- Always-on agents

---

## Safety and integrity boundaries

The pipeline automates aggressively but never crosses these lines:

- ❌ Do not lie on resumes or application forms
- ❌ Do not invent employers, degrees, dates, certifications, tools, or production experience
- ❌ Do not bypass CAPTCHA, MFA, identity checks, or anti-bot protections
- ❌ Do not use proxy rotation, fingerprint spoofing, solver services, or fake identities
- ❌ Do not commit credentials, cookies, resumes, personal configs, or private emails to Git
- ❌ Do not submit false answers to knockout questions

If a CAPTCHA, MFA challenge, or identity check appears, the pipeline **pauses** and marks the application as requiring manual checkpoint completion.

---

## Architecture

The system is a **scheduled local batch process**. It runs once per day, writes all state to SQLite and disk, produces a daily report, and exits.

### CLI

```bash
# Full daily run
python -m job_pipeline run daily

# Step-by-step
python -m job_pipeline fetch
python -m job_pipeline validate
python -m job_pipeline rank
python -m job_pipeline build-packets
python -m job_pipeline submit
python -m job_pipeline monitor-mail
python -m job_pipeline report

# Dry run (no submission, no email)
python -m job_pipeline run daily --dry-run
```

### Orchestrator responsibilities

The orchestrator (`src/job_pipeline/orchestrator.py`) coordinates the run. It must stay small — no scraping logic, no SQL schema definitions, no browser automation internals. Coordination only.

---

## Discovery layer

The pipeline does not require a target company list. Discovery is keyword-driven.

**What matters:** connection to AI work — not which company is posting.

### Discovery sources

| Source | Method |
|---|---|
| Indeed | Keyword search via URL params (`/jobs?q=...&l=...`) |
| Greenhouse job board | Public board index + keyword filter |
| Lever job board | Public board index + keyword filter |
| Microsoft Careers | Dedicated fetcher with keyword filter |

### Keyword strategy

Discovery queries are defined in config and cover the full AI/ML evaluation space:

```yaml
discovery:
  keywords:
    - "LLM evaluation"
    - "AI model quality"
    - "prompt evaluation"
    - "AI data quality"
    - "model behavior"
    - "red teaming"
    - "RLHF"
    - "AI evaluator"
    - "data labeling AI"
    - "AI tooling"
    - "frontend AI"
    - "applied AI"
  location: "Remote"
  additional_locations:
    - "City, State"
    - "Another City, State"
  max_results_per_query: 50
```

High recall is the goal at this stage. Irrelevant results get filtered in the validation and scoring steps — not here.

### URL resolution

When a job is found on Indeed or another mirror, the pipeline attempts to resolve the original ATS source:

```
Indeed listing
  → follow redirect or parse job URL
  → detect Greenhouse / Lever domain pattern
  → if found: use ATS URL as canonical source
  → if not found: keep Indeed URL
```

This is how the pipeline finds Greenhouse and Lever jobs without maintaining a company list.

---

## Supported sources

| Source | Role |
|---|---|
| Greenhouse | Preferred ATS source |
| Lever | Preferred ATS source |
| Indeed | Discovery entry point + mirror |
| Microsoft Careers | Source-specific fetcher + browser automation |

When the same role exists on both Indeed and Greenhouse, the pipeline prefers **Greenhouse**.

Original ATS sources are always preferred over mirrors.

---

## Scoring and ranking

Scoring runs after validation and deduplication, before resume tailoring. Its job is to decide which jobs get a tailoring slot in today's run.

**Scoring is lexical, not semantic.** No LLM is used for scoring.

### Score components

| Signal | Weight | Notes |
|---|---|---|
| Skill keyword overlap | Primary | Match against `truth_profile.skills.*` |
| Title match | Bonus | Job title ∈ `allowed_titles` or close variant |
| Location match | Bonus | Remote or candidate location |
| Already applied | Penalty | Applied within last 60 days, JD unchanged |
| company_memory rejection | Penalty | Auto-rejected within 90 days |

### Keyword overlap calculation

```python
# Pseudocode
def score_job(job, truth_profile):
    jd_tokens = tokenize(job.description + job.title)
    skill_tokens = flatten(truth_profile.skills)

    matched = [s for s in skill_tokens if s.lower() in jd_tokens]
    overlap_ratio = len(matched) / len(skill_tokens)

    score = overlap_ratio * 100
    if job.title in truth_profile.allowed_titles:
        score += 15
    if is_remote(job) or matches_location(job):
        score += 10
    if recently_applied(job):
        score -= 40
    if recently_rejected_by_company(job.company):
        score -= 20

    return score
```

### Slot allocation

Daily slots are filled in descending score order. Low-scoring jobs (below configurable threshold) are stored but not submitted.

```yaml
scoring:
  min_score_to_submit: 25
  max_slots_per_run: 30
  max_slots_per_company: 5
```

---



Naive scraping is not enough. Every fetched page is validated before entering the corpus.

### Required fields

- Job title
- Company name
- Location or remote marker
- Description with sufficient length
- Requirements or responsibilities section
- Apply URL or identifiable application mechanism

### Extraction priority

```
Structured API
  → Embedded JSON
  → JSON-LD JobPosting
  → DOM extraction
  → Visible text
  → LLM cleanup (last resort only)
```

Never call the LLM for extraction when structured data exists.

### Rejection signals

The validator rejects pages that look like: blog posts, search results, privacy pages, expired listings, or generic company landing pages.

---

## Deduplication and job families

Deduplication is memory, not deletion. Duplicates are linked, not removed.

### Job family matching

A job family is inferred from:

- Company
- Title
- Location
- Source job ID (when available)
- URL
- Description similarity

### Policy

| Condition | Action |
|---|---|
| Company + title + location match | Likely same family |
| Description similarity ≥ 90% | Same role family |
| Description changed ≥ 30% | Treat as meaningful new version |
| Same role applied recently + JD unchanged | Create human decision item |
| Repost after previous application, no reply | Ask whether to apply again |

---

## Resume tailoring

Mode: **aggressive but truth-bound**.

### Allowed operations

- Change target title at the top of the resume
- Reorder skills to match job description
- Rewrite summary text
- Reframe projects toward the job description
- Mirror terminology from the job description
- Emphasise matching experience
- Generate a different PDF for every application

### Never allowed

- Invent experience
- Invent skills
- Claim tools not in the truth profile
- Claim production experience that does not exist
- Claim degrees, certifications, dates, or employers that are not real

### Source of truth

The **truth profile** (`truth_profile.yaml`) is the source of truth — not the base resume.

---

## Truth profile

```yaml
candidate:
  name: null
  location: null
  language: "English"

allowed_titles:
  - "Applied AI Specialist"
  - "LLM Evaluation Specialist"
  - "AI Model Quality Analyst"
  - "Prompt Evaluation Specialist"
  - "AI Tooling Developer"
  - "Data Quality Analyst"
  - "Frontend AI Tools Developer"

skills:
  ai:
    - LLM evaluation
    - model behavior evaluation
    - prompt testing
    - red teaming
    - LoRA
    - DPO-style workflows
    - synthetic datasets
    - human-authored datasets
    - refusal quality
    - persona consistency
    - LLM-as-judge auditing
    - small/local model optimization
    - quantization
    - PyTorch
    - Python
    - Hugging Face
    - Ollama
    - Unsloth

  frontend:
    - React
    - JavaScript
    - TypeScript
    - HTML
    - CSS
    - Vite
    - WordPress
    - REST API integration
    - browser local/session storage

  data_quality:
    - computer vision annotation
    - object detection
    - segmentation
    - autonomous vehicle perception datasets
    - QA
    - random sampling
    - human adjudication

  production:
    - game production
    - character systems
    - creative direction
    - outsourcing pipelines
    - cross-functional collaboration

forbidden_claims:
  - production C++
  - H.264 / H.265
  - video codec engineering
  - CUDA kernel development
  - GPU compiler engineering
  - driver development
  - active security clearance
  - PhD
  - Azure production deployment
  - Kubernetes production operations

allowed_mappings:
  character design: "persona / behavior design"
  prompt testing: "LLM evaluation"
  local model experiments: "small/local model optimization"
  React prototype: "frontend AI tooling"
  CV annotation: "computer vision data quality"
  QA testing: "quality assurance / evaluation"
```

---

## Truth guard

The truth guard runs after resume tailoring and before PDF rendering.

It checks every generated resume against the truth profile and rejects any claim that is not in `skills`, not in `allowed_mappings`, or explicitly listed in `forbidden_claims`.

A failed truth guard produces a `truth_guard_failed` status and blocks submission.

---

## Submission strategy

### ATS tiers

| Tier | ATS | Strategy |
|---|---|---|
| 1 | Greenhouse | Native API / known DOM — highest success rate |
| 1 | Lever | Native API / known DOM — highest success rate |
| 2 | Workday, iCIMS, Taleo, others | Playwright best-effort |
| 3 | Email-apply | Direct email submission |

### Tier 2: Playwright best-effort

For any ATS not in Tier 1, the pipeline attempts Playwright form automation with a best-effort approach:

```
Open application URL
→ Detect visible form fields
→ Fill known field types: name, email, phone, location, resume upload, cover note
→ Attempt multi-page navigation (Next, Continue buttons)
→ Detect CAPTCHA / MFA / identity challenge → STOP, mark manual_checkpoint_required
→ Attempt submit
→ Detect confirmation page → submitted_verified
→ No confirmation → submitted_unverified
→ Any unrecoverable error → submit_failed, log field that broke
```

The pipeline does not retry on failure. It logs the failure, stores the application packet, and surfaces it in the debug report so a human can submit manually if desired.

### Checkpoint policy

When automation hits a wall (CAPTCHA, MFA, unusual identity field, legal attestation), the pipeline:

1. Pauses that application
2. Sets status: `manual_checkpoint_required`
3. Saves the pre-filled application packet to artifacts
4. Adds a human decision item to the report

The candidate can then open the application, complete the checkpoint, and submit. The pipeline stores what it prepared regardless.

### Field detection heuristics

Playwright form filler uses label text, input `name`, `id`, and `aria-label` attributes to identify fields. Known mappings:

```yaml
field_mappings:
  name: ["full name", "your name", "applicant name"]
  email: ["email", "e-mail", "email address"]
  phone: ["phone", "mobile", "telephone"]
  resume: ["resume", "cv", "upload resume", "attach resume"]
  cover_letter: ["cover letter", "cover note", "message"]
  linkedin: ["linkedin", "linkedin url", "linkedin profile"]
  location: ["location", "city", "where are you located"]
```

Unknown required fields trigger `submit_failed` with the field label logged.

---



For every submitted application, the system stores:

| Field | Notes |
|---|---|
| Job source | Greenhouse, Lever, Indeed, etc. |
| Company | |
| Title | |
| Location | |
| Original job URL | |
| Application URL | |
| Job description snapshot | Full text |
| Description hash | SHA-256 |
| Resume JSON | Forever |
| Resume text | Forever |
| Resume PDF | 30 days unless positive reply |
| Resume hash | |
| Cover note | |
| Form answers | |
| Submit result | |
| Confirmation text | If captured |
| Email confirmation | If captured |
| Model used for tailoring | |
| Prompt hash | |
| Truth guard report | |
| Application status | |
| Event history | JSONL |

---

## Application status values

```
submitted_verified          # Confirmation page or email captured
submitted_unverified        # Submit completed, no confirmation captured
fetch_failed
validation_failed
low_quality_scrape
tailor_failed
truth_guard_failed
pdf_render_failed
submit_failed
confirmation_missing
email_link_failed
manual_checkpoint_required  # Blocked by CAPTCHA / MFA
human_decision_pending      # Requires human input
```

---

## Email handling

### Categories

```
application_confirmation
auto_rejection
positive_reply
assessment_request
interview_request
scheduling
newsletter_or_noise
unknown
```

### Hidden (noise)

- Automated rejection bodies
- "We moved forward with other candidates"
- "After careful consideration"
- Any rejection without next steps

### Surfaced (signal)

- Interview requests
- Assessment requests
- Scheduling emails
- Recruiter replies that ask for next steps
- Any message that indicates forward motion

> A machine-generated positive signal is useful if it advances the process.
> A human rejection is still not useful unless it contains a next step.

---

## Human decision queue

The pipeline asks for human input only when genuinely required:

- Similar role already applied to recently
- Repost detected after a previous application
- Job description changed ≥ 30%
- Legal or identity question not covered by config
- Form cannot be answered truthfully from the truth profile
- Submit flow blocked by CAPTCHA, MFA, or identity challenge

Normal applications do not require approval.

---

## Daily report

```
Daily run report - 2026-05-27

Submitted:
  Company A | AI Model Quality Analyst    | Greenhouse | submitted_verified   | artifacts/.../resume.pdf
  Company B | Prompt Evaluation Specialist | Lever      | submitted_unverified | artifacts/.../resume.pdf
  Company C | Data Quality Analyst         | Greenhouse | submitted_verified   | artifacts/.../resume.pdf

Needs decision:
  Company D | AI Evaluator | Similar role applied 34 days ago, JD changed 42% | recommended: apply again

Failed / debug:
  Company E | Apply form changed — missing required field
  Company F | PDF upload failed

Positive signals:
  Company G | assessment_request
  Company H | interview_request
```

The report never shows rejection text.

---

## LLM cost controls

The LLM is not called for everything. Cheap deterministic steps run first.

| Step | LLM? |
|---|---|
| Fetch | No |
| Deduplication | No |
| Lexical scoring | No |
| Job extraction (likely jobs only) | Yes — cheap model |
| Resume tailoring (submit candidates only) | Yes — better model |
| Email classification | Yes — cheap model |

Every LLM result is cached. The same job snapshot + base resume version + prompt hash + model never triggers a second call.

### Model routing (configurable)

```yaml
llm:
  provider: "openrouter"
  max_cost_per_run_usd: 0.50
  max_tailored_resumes_per_run: 30
  cache_llm_outputs: true

  routing:
    extractor:
      model: "google/gemini-2.0-flash-lite-001"
      temperature: 0.0
      max_tokens: 1200

    tailor:
      model: "anthropic/claude-3.5-haiku"
      temperature: 0.2
      max_tokens: 5000

    fallback_tailor:
      model: "openai/gpt-4o-mini"
      temperature: 0.2
      max_tokens: 5000

    classifier:
      model: "google/gemini-2.0-flash-lite-001"
      temperature: 0.0
      max_tokens: 800
```

---

## Artifact retention

```yaml
retention:
  keep_resume_json_forever: true
  keep_resume_text_forever: true
  keep_resume_pdf_days_without_reply: 30
  keep_pdf_if_positive_reply: true
  keep_job_snapshots_forever: true
  keep_email_bodies_for_positive_replies: true
  quarantine_rejection_bodies: true
```

---

## Artifact layout

```
artifacts/
  applications/
    2026-05-27_greenhouse_company-slug_jobid/
      job/
        snapshot.json
        clean_description.txt
        raw.json
      resume/
        tailored_resume.json
        tailored_resume.pdf
        tailored_resume.txt
        diff_summary.md
        truth_guard.json
      submission/
        cover_note.txt
        form_answers.json
        confirmation.txt
        submit_result.json
      events.jsonl
```

Artifacts are never committed to Git.

---

## Company memory

The `company_memory` table is the pipeline's institutional knowledge about each company. It feeds scoring penalties, human decision triggers, and daily limit checks.

### Schema

```sql
CREATE TABLE company_memory (
    id                        INTEGER PRIMARY KEY,
    company_slug              TEXT NOT NULL UNIQUE,
    company_name              TEXT NOT NULL,

    -- Application history
    total_applications        INTEGER DEFAULT 0,
    last_application_date     DATE,
    last_applied_role         TEXT,
    last_applied_role_result  TEXT,  -- submitted_verified | auto_rejected | no_reply | interview

    -- Rejection tracking
    total_auto_rejections     INTEGER DEFAULT 0,
    last_rejection_date       DATE,
    last_rejection_type       TEXT,  -- auto_rejection | human_rejection | ghosted

    -- Role history: JSON array of {title, date, status, resume_hash}
    roles_applied             TEXT,

    -- Human notes
    blacklisted               BOOLEAN DEFAULT FALSE,
    blacklist_reason          TEXT,
    priority_boost            INTEGER DEFAULT 0,  -- -2 to +2
    notes                     TEXT,

    updated_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### How it drives decisions

| Situation | Check |
|---|---|
| Scoring | `last_rejection_date` within 90 days → score penalty |
| Scoring | `roles_applied` contains same title → score penalty |
| Slot allocation | `blacklisted = true` → skip entirely |
| Human decision | Same role + `last_applied_role_result = no_reply` → ask |
| Daily limit | Applications today for this company → enforce cap |

company_memory is updated after every submission, email classification, and manual status change.

---

## Database

SQLite for the MVP. Single-user, local, scheduled — SQLite is sufficient.

### Core tables

| Table | Purpose |
|---|---|
| `companies` | Company registry |
| `job_families` | Grouped related postings |
| `job_postings` | Individual postings |
| `job_snapshots` | Description snapshots with hashes |
| `applications` | Application records |
| `resume_variants` | Generated resume versions |
| `submission_artifacts` | Paths to artifacts per submission |
| `application_events` | Status event log |
| `email_messages` | Classified emails |
| `human_decisions` | Pending human decisions |
| `company_memory` | Per-company history and context |

The database stores metadata. Large artifacts live on disk.

---

## Project structure

```
job-application-pipeline/
  README.md
  pyproject.toml
  .gitignore
  .env.example
  config.example.yaml

  prompts/
    extract_job.md
    tailor_resume.md
    truth_guard.md
    cover_note.md
    email_classifier.md

  examples/
    truth_profile.example.yaml
    base_resume.example.json
    greenhouse_job.example.json
    rejection_email.example.txt
    positive_reply.example.txt

  src/
    job_pipeline/
      __init__.py
      cli.py
      orchestrator.py
      config.py
      logging.py

      db/
        schema.sql
        connection.py
        repository.py

      sources/
        base.py
        greenhouse.py
        lever.py
        indeed.py
        microsoft.py

      discovery/
        keywords.py         # keyword config + query builder
        indeed_search.py    # Indeed keyword search → raw URLs
        ats_resolver.py     # resolve Indeed → Greenhouse/Lever canonical URL
        scheduler.py        # which queries to run today

      extraction/
        html_cleaner.py
        jsonld.py
        job_validator.py
        snapshot.py

      matching/
        dedupe.py
        similarity.py
        family_linker.py
        scoring.py

      llm/
        openrouter.py
        cache.py
        prompts.py

      resume/
        tailor.py
        merge.py
        truth_guard.py
        render_html.py
        render_pdf.py

      submit/
        base.py
        greenhouse.py
        lever.py
        playwright_form.py
        email_submit.py

      gmail/
        auth.py
        monitor.py
        classify.py
        labels.py

      artifacts/
        writer.py
        cleanup.py

      reports/
        daily.py
        export_csv.py

  tests/
    test_job_validator.py
    test_dedupe.py
    test_truth_guard.py
    test_resume_merge.py
    test_email_classifier.py
    test_scoring.py
    test_ats_resolver.py
    test_company_memory.py
    test_playwright_field_mapper.py
```

---

## File size rule

**No Python file may exceed 300 lines.** Hard rule.

When a file approaches 300 lines, split it. One concern per file.

| Bad | Good |
|---|---|
| `JobFloodAgent.py` (everything) | `sources/greenhouse.py` |
| | `resume/tailor.py` |
| | `resume/truth_guard.py` |
| | `submit/playwright_form.py` |
| | `gmail/monitor.py` |

---

## Configuration

```yaml
run:
  mode: "scheduled"
  schedule: "daily"
  timezone: "America/Los_Angeles"
  max_applications_per_day: 30
  max_applications_per_company_per_day: 5
  language: "en"

sources:
  greenhouse: true
  lever: true
  indeed: true
  microsoft_careers: true

submission:
  prefer_original_ats_over_mirror: true
  greenhouse_over_indeed: true
  save_confirmation_text: true
  screenshots: false
  treat_submit_without_confirmation_as: "submitted_unverified"

dedupe:
  description_same_threshold: 0.90
  description_changed_threshold: 0.30
  ask_human_on_reapply: true
  delete_duplicates: false
  link_duplicates_to_family: true

resume:
  mode: "aggressive"
  allow_target_title_change: true
  keep_json_forever: true
  keep_pdf_days_without_reply: 30
  keep_pdf_if_positive_reply: true

forms:
  answer_no_to_unsupported_requirements: true
  continue_after_no_on_knockout: true
  demographics:
    veteran_status: "No"
    disability_status: "Prefer not to answer"
    gender: "Prefer not to answer"
    race_ethnicity: "Prefer not to answer"

email:
  hide_auto_rejections: true
  show_positive_replies_only: true
  show_assessment_requests: true
  show_interview_requests: true
  show_scheduling: true
```

---

## Environment variables

```bash
OPENROUTER_API_KEY=...
GMAIL_CLIENT_SECRET_PATH=...
GMAIL_TOKEN_PATH=...
DATABASE_PATH=data/jobs.sqlite
ARTIFACTS_DIR=artifacts
```

Never commit `.env`.

---

## Git ignore policy

```gitignore
.env
*.sqlite
*.db
artifacts/
data/
resumes/private/
gmail_token.json
credentials.json
cookies/
browser_profiles/
__pycache__/
.pytest_cache/
```

---

## Testing

Tests are required for anything that can silently corrupt state.

| Test | Why |
|---|---|
| `test_job_validator.py` | Bad pages silently enter corpus |
| `test_dedupe.py` | Duplicate submissions are costly |
| `test_truth_guard.py` | False claims are a hard failure |
| `test_resume_merge.py` | Silent data loss in merge |
| `test_email_classifier.py` | Misclassified rejections surface as signal |

Plus: URL normalisation, description hash / change ratio, artifact writer, retention cleanup.

```bash
pytest
```

---

## Failure handling

One failed job never kills the run. Every failure becomes a labelled status and appears in the debug section of the daily report.

---

## Structured logging

Every log event includes:

```json
{
  "timestamp": "2026-05-27T08:14:03Z",
  "source": "greenhouse",
  "company": "Acme Corp",
  "job_title": "AI Model Quality Analyst",
  "job_id": "abc123",
  "application_id": "app_789",
  "event_type": "submit",
  "status": "submitted_verified",
  "error": null
}
```

Logs are written as JSONL.

---

## MVP phases

### Phase 1 — Job corpus and provenance

Build: SQLite schema · artifact writer · Greenhouse source · Lever source · job validator · dedupe / job family linker · daily report

> Fetch jobs, validate them, snapshot them, link them, store them.

---

### Phase 2 — Resume packet generation

Build: truth profile loader · OpenRouter client · resume tailor · truth guard · HTML renderer · PDF renderer · application packet writer

> For selected jobs, generate tailored resume JSON, text, PDF, cover note, and diff report.

---

### Phase 3 — Submission

Build: Greenhouse submit · Lever submit · Playwright form filler · email submitter · application status tracking · confirmation detection

> Submit applications and store exactly what was sent.

---

### Phase 4 — Email firewall

Build: Gmail OAuth · message monitor · rejection classifier · positive reply classifier · labels · daily report integration

> Hide rejection noise. Surface only next steps.

---

### Phase 5 — Dashboard

Build: local dashboard · application history · resume variant viewer · decision queue · positive signal inbox · company memory

> Make the system inspectable without exposing the user to rejection sludge.

---

## Tech stack

```
Python 3.11+
```

**Core dependencies:**

```
requests          httpx             beautifulsoup4    lxml
pydantic          pyyaml            sqlite3           rapidfuzz
python-dotenv     jinja2            weasyprint        playwright
google-api-python-client           google-auth-oauthlib
```

**Optional (later phases):**

```
duckdb            fastapi           streamlit         typer
rich              sentence-transformers
```

**LLM provider:** OpenRouter API

---

## Intended audience

This project is for:

- Job seekers managing high-volume applications
- People who want reproducible resume tailoring
- People who need provenance: knowing exactly what a company received
- People who want automated rejection noise filtered out
- Engineers experimenting with local automation pipelines

It is not for bypassing anti-bot systems, generating fake resumes, fabricating experience, evading bans, impersonation, credential stuffing, or scraping private data.

---

> Built on three rules:
>
> **Do not lie.**
> **Do not lose provenance.**
> **Do not waste human attention on automated rejection noise.**
