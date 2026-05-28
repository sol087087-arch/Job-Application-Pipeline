# Candidate Profile Data

The tailoring system should not treat a base resume as the source of truth.
It should use a private master profile as an evidence bank.

Use this flow:

1. Copy `config/profile/master_profile.example.yaml` to `private/master_profile.yaml`.
2. Fill `private/master_profile.yaml` with real evidence bricks, projects, links, dates, tools, and measurable outcomes.
3. Keep `private/master_profile.yaml` out of git.
4. Tailoring can rephrase an evidence brick for ATS fit, but every generated resume claim must map back to a brick or an allowed mapping.
5. Truth guard blocks forbidden claims and any unsupported generated claim.

The goal is autopilot:

- Do not ask the user to approve every resume.
- Regenerate once if truth guard fails.
- Submit automatically if truth guard passes.
- Ask the user only for CAPTCHA/login, legal ambiguity, unsupported required answers, or reapply ambiguity.

Form filling is part of the same profile. The `form_answer_defaults`,
`field_mappings`, and `short_answer_bank` sections are meant to let the
submission backend answer routine forms immediately:

- Contact, resume upload, cover note, source, referral, EEO, and demographics should be filled without user review.
- Legal/work authorization fields may be automated only after the private profile has explicit true/false values.
- Unknown optional fields should be left blank.
- Unknown required fields should create a manual checkpoint with the application URL and saved prepared packet.
- CAPTCHA, MFA, login, identity verification, and file upload failures should be sent to Telegram as action links.
