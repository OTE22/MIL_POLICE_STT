# Intake, report editing, and dictation lineage

Status: implementation and validation in progress. This document is not a deployment certificate.

The runtime requirements catalogue is `app/services/participant_requirements.py`, exposed by
`GET /api/investigations/participant-requirements`. Its keys, applicability, exception choices,
stage, and canonical paths drive the setup form and API readiness checks. Readiness responses
include a participant key, field key, explanation, and navigation target.

| Frontend control | API input | Canonical database owner | Report use / issued snapshot |
|---|---|---|---|
| Recorded name / designation | subjects[].subject_name | subjects.subject_name; canonical current display resolves subjects.identity_id → person_identities.person_name | statement_name and frozen person_snapshot |
| Person type | subjects[].person_type | subjects.person_type | Conditional intake requirements and report presentation |
| Father's name | subjects[].statement_details.father_name | subjects.statement_details.father_name | statement.values.father_name |
| Mother's name | subjects[].statement_details.mother_name | subjects.statement_details.mother_name | statement.values.mother_name |
| Birth year | subjects[].statement_details.birth_year | subjects.statement_details.birth_year | statement.values.birth_year; numeric year validated |
| Birthplace | subjects[].statement_details.birth_place | subjects.statement_details.birth_place | statement.values.birth_place |
| Birth district | subjects[].statement_details.district | subjects.statement_details.district | statement.values.district |
| Residence | subjects[].statement_details.residence | subjects.statement_details.residence | statement.values.residence |
| Phone | subjects[].statement_details.phone | subjects.statement_details.phone | statement.values.phone |
| Family status | subjects[].statement_details.family_status | subjects.statement_details.family_status | statement.values.family_status |
| Education | subjects[].statement_details.education | subjects.statement_details.education | statement.values.education |
| Occupation / military role | subjects[].statement_details.occupation_statement | subjects.statement_details.occupation_statement; untouched military fallback reuses rank/unit/department | statement.values.occupation_statement |
| Prior convictions declaration | subjects[].statement_details.prior_record_statement | subjects.statement_details.prior_record_statement | statement.values.prior_record_statement; an attributed declaration, not a verified criminal-record lookup |
| Military branch | subjects[].security_branch | subjects.security_branch | Namespace of service identifier; military applicability |
| Rank | subjects[].rank | subjects.rank | statement_rank and occupation fallback |
| Service number | subjects[].military_id | subjects.military_id; canonical scoped identifier registry | statement_service_number |
| Unit | subjects[].unit | subjects.unit | occupation fallback |
| Nationality | subjects[].nationality_code / nationality_name | subjects.nationality_code / nationality_name | Civil-registration applicability; frozen source facts |
| Register number | subjects[].register_number | subjects.register_number; canonical scoped identifier registry | civil_register |
| Registration district | subjects[].caza_code | subjects.caza_code | Identifier scoping; frozen source facts |
| Registration place | subjects[].place_of_registration | subjects.place_of_registration | civil_register |
| Unregistered situation | subjects[].is_unregistered | subjects.is_unregistered | Civil-registration exception in presentation, no invented identifier |
| Identity document situation | subjects[].documents / is_undocumented / undocumented_reason | subject_documents; subjects.is_undocumented / undocumented_reason | Evidence links and frozen source snapshot; does not assert verification |
| Unknown/refused/not applicable | subjects[].field_exceptions[field] | subjects.field_exceptions | Separate reasoned exception, formatted only when assembling the report; author/time/revision stamped by server |
| Subject | title | investigation_sessions.title | Initial report subject; explicit report override retained |
| Location/date | location/session_date | investigation_sessions.location/session_date | Initial closing defaults; frozen issued facts |
| Lead/assistants | investigators[] | session_investigators → investigator_profiles → users | Assigned identities, report signer defaults, lead approval authorization |
| Report subject/signer/clerk | document.subject/investigator_id/clerk_id | report_drafts.official_form.html_report | Editable document selection; IDs must belong to this session |
| Statement person | blocks[].participant_key | subjects.participant_key | Stable selection, person_snapshot, immutable issued document |
| Statement text and Q/A | statement.entries[] | report_drafts.official_form.html_report.blocks | Draft wording; source QA IDs/snapshots retain recording/segment provenance |
| Identity verification | statement.identity_checked + identity_documents | report JSON | Explicit later-stage clause; never enabled during intake |
| Statement attestation | statement.attestation_confirmed | report JSON | Explicit later-stage clause; clerk required when confirmed |
| Note body/date/time | note.values.note_text/note_date/note_time | report JSON | Separate action date/time and closing/signing date |
| Optional wording template | note.template_id/template_values | report_note_templates and server template_snapshot | Fixed blank wording, filled variables; no sample incident facts copied |
| Closing/signature details | block.values.closing_date/closing_location/*_name | report JSON overrides of session defaults | Issued immutable signer facts |
| Facts / inference | conclusion.values.facts/inference | report JSON, exactly one conclusion | Investigator-authored narrative |
| Responsibility decision | conclusion.responsibility_mode | report JSON | UNREVIEWED, FINDINGS, or explicit NONE |
| Responsibility finding | conclusion.findings[] | report JSON; participant_key references subjects, references point to session evidence | Author-written finding plus frozen resolved subject name |
| Proposals decision/text | conclusion.proposal_mode + values.proposals | report JSON | UNREVIEWED, TEXT, or explicit NONE; contradictory text/none blocked |
| Supporting references | note/conclusion/finding.references | Existing participant/document/recording/report-block IDs | Same-session validation; no new evidence entity |
| Dictation destination | block_id + field | audio_recordings.report_context | Explicit report draft, block, field, original destination digest |
| Dictation audio | existing agent token/audio APIs with signed purpose | audio_recordings.purpose=REPORT_DICTATION, storage_path, sha256 | Original audio retained, separate from interview lists/imports |
| Machine dictation | agent result API | audio_recordings.report_context.result + machine_text | Original engine output retained, no Transcript or SessionSpeaker rows |
| Accepted dictation | dictation accept API | report_context accepted_text/by/at/mode; report block dictation_sources | Explicit accepted wording and provenance frozen at issuance |
| Dismissed dictation | dictation dismiss API | report_context dismissed_by/at/reason | Retained and audited; no implicit deletion |
| Autosave token | expected_token | report_drafts.revision plus content hash | Serialized compare-and-save; conflict keeps local work |
| Approval | expected report/source tokens | official_form.html_review | Bound to content, sources, renderer digest, assigned lead |
| Transcript review | expected_token + explicit review action | transcripts.review_token/reviewed_by/reviewed_at | Hash binds text revisions, attribution and speaker identity; corrections invalidate review; issued context freezes review provenance |
| Official output | explicit issue API | generated_reports + immutable HTML/PDF/context files and hashes | Continuous version numbers; corrections retain original files |

## Duplication decisions

- Participant statement-details controls live in setup. The detail screen links there.
- Canonical current identity names and session-specific recorded declarations are distinct owners.
- Report person snapshots, source text snapshots, and issued files are deliberate historical copies.
- Edited report wording is an explicit override; source refresh offers comparison and acceptance.
- Approved wording is not automatically refreshed on an unrelated draft save.
- Dictation uses existing recordings/jobs with an explicit purpose. It does not create a second
  participant, transcript, speaker, or evidence schema.
- Missing values do not become placeholder names/identifiers. Exceptions are separate metadata.
- Omitted participant/document facts are retained. Explicit removals preserve the historical rows.

## Migration chain

`c832456a7e12 → d943567b8f23 → e054678c9a34 → f165789dab45` adds exception metadata and recording purpose/context,
widens the archive format constraint, and adds explicit transcript review provenance. Existing recording purpose defaults to INTERVIEW.
Existing report archives and hashes are not rewritten. Downgrades that would discard new
provenance or issued-format support are refused; repair forward.
