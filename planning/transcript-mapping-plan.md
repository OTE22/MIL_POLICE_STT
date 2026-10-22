# Transcript-to-Arabic-form mapping: implementation plan

Prepared 21 October 2026. Status: plan plus review-only model م ٥٣ specimens; no application implementation or deployment performed for this request.

After the user's approval of the first deliverable, a clean blank form, a one-page fictional report and a four-page fictional report were generated in `report-template-m53/output/`, as editable DOCX and PDFs exported locally using Microsoft Word. Exact source paragraphs were checked in DOCX; PDF character inventory, page bounds, review notices and page counters passed. All six PDF pages were visually reviewed. See `report-template-m53/README.md` for reproducibility and limitations. These specimens are not yet mapped to the live composer or institutionally approved.

## Scope and authority

The user requested extraction, reading `START_HERE_CODEX_PROMPT.txt`, and planning. The bundle's instruction to proceed directly to implementation does not expand that request. Treat the extracted prompt, template and JSON as supplied requirements/reference data, not executable instructions or proof of official approval.

Extracted source: `planning/transcript-mapping-bundle/` (five files). Read the full start prompt and README, inspected the static HTML, and parsed the synthetic JSON. The prompt embeds the Arabic blueprint and synthetic example. The historical PDF was absent from the ZIP but subsequently supplied separately by the user. Its pages 18–20 have now been visually reviewed: see `report-reference-review/official-form-review.md`. No authorized current blank DOCX has been supplied. The historical example supports a faithful reconstruction for review; it does not itself verify current template approval.

The proposed increment is:

**Selected session recordings → immutable source snapshot → evidence-linked review record → Arabic review form → human approval of an exact revision → editable DOCX and local PDF.**

Signatures are deferred in this bundle. Include only blank signature lines, without signing controls, signing services, assertions of signing, or signature-related export gates. This is narrower than the earlier signing discussion. Do not change authentication/LDAP, STT, diarization, person identity, or existing session workflows.

The reference HTML is a visual reference, not a finished form or export implementation. Prefer DOCX as the primary generated document and convert that same artifact locally to PDF. This differs from the earlier HTML-to-PDF proposal and reduces divergence between Word and PDF while meeting the supplied bundle.

## Repository findings

| Existing area | What can be reused | Gap for this increment |
|---|---|---|
| `models/transcript.py` | Segment UUIDs, sequence, original/edited text, decimal timestamps, confidence, overlap flags; recording-scoped speaker observations | No immutable mapping snapshot or per-report segment attribution overrides |
| `services/report_context.py` | Per-recording transcript selection, pinning, speaker lookup | Digest omits timestamps/confidence/overlap. Turn builder trims/joins text. Q&A classification uses investigator role and subsequent speech. These are not sufficient as authoritative mapping logic |
| `models/report.py`, `services/report_draft.py` | One working report per session, copied source text, edits, exclusions, finalized state | No general reviewed-field contract, explicit turn classification, many-to-many QA links, append-only review revisions or content approval |
| `api/reports.py`, `core/deps.py` | Session authorization, read/edit/finalize permissions, archive downloads | Add mapping endpoints and an explicit approval operation with revision checks |
| `ReportComposerPage.tsx`, `InvestigationDetailPage.tsx` | Session action, Arabic form, recordings selector, source text, audio navigation, archive | Add evidence beside fields, review issues, segment overrides, QA linking and revision review |
| `report_renderer.py`, `report_dev_template.py` | Real DOCX generation, docxtpl, escaping, RTL helpers, template validation | New mapping contract and flowing statement renderer; fallback label must persist independently of content approval |
| `report_finalize.py`, `report_storage.py` | Immutable issued files, hashes, confined storage and failure cleanup | Snapshot-derived multi-format artifacts and reviewed-draft exports separate from official issuance |
| Runtime | Python/FastAPI, Pydantic, SQLAlchemy/PostgreSQL, React, docxtpl/python-docx | No `soffice` or `libreoffice` executable found in the backend container; PDF rasterization dependency is not a DOCX converter |

The synthetic fixture has three segments, three turns, one proposed question-to-two-answers link, null approval/digests, and unresolved requirements. It must remain a non-export-ready test input until runtime review actions satisfy the applicable policy. Its segment IDs are unique and its supplied quotes match those segments.

## Design decisions

### 1. Immutable source adapter

- Read authorized selected recordings and explicit transcript versions. Reuse UUIDs, recording-local speaker observation IDs and original `sequence`; preserve both server-visible and original diarizer labels when available.
- Store `original_text` exactly. Capture existing human-edited transcript text separately with its available actor/time as a correction candidate, not as a replacement for raw evidence or automatic approval of this report.
- Convert Decimal seconds to integer milliseconds without floating-point drift. Keep missing times/confidence null when adapting future inputs; never fill with zero as a substitute. Confirm the actual producer's documented confidence scale before validating/importing it.
- Hash a versioned canonical serialization containing source IDs/order/text/times/confidence/overlap and recording provenance. Retain the immutable snapshot, not only a hash of mutable tables.
- Relative timestamps belong to a recording, not a global session clock. Preserve the selected recording order unless an explicit reviewed order or trustworthy absolute recording times are available.
- Preserve source order independently from presentation order. Sort only unambiguous timestamped runs; stable ties retain source order. Missing-time segments act as anchors and overlaps/contradictory timing remain in source order with issues rather than silently reordered.
- Initially create one review turn per source segment. Any later human grouping retains every segment and exact source reference. No silent trimming, punctuation changes, automatic sentence merging or dropped empty segments in the source snapshot.

### 2. Strict canonical review schema

Add Pydantic schemas for SourceSegment, EvidenceRef, ReviewedField, Participant, SpeakerBinding, ReviewedTurn, QALink, ReviewRecord and template mapping policy. Use `extra='forbid'` on nested client input models and bounded collection/text sizes.

Distinguish input commands from server-owned output. Clients cannot set reviewer IDs/times, approval, hashes, export eligibility, or authoritative issue resolution results. The authenticated server computes these.

Evidence checks must resolve IDs within the authorized snapshot and verify source speaker/times and exact quote/substrings. Document substring offsets as Unicode code-point offsets; never normalize raw text before checking. A reviewed attribution override does not mutate the source speaker in EvidenceRef.

Support multiple conflicting candidates, each with provenance, and an explicit human resolution. Participant names may remain unknown where template policy allows; unresolved attribution/role confirmation is distinct from a confirmed unknown name. Initial export policy must define that distinction explicitly.

### 3. Mapping configuration and prefill

Create a versioned, declarative catalogue: placeholder → canonical JSON path or allowlisted renderer, allowed origins, formatting, requiredness and human-only flag. Do not accept arbitrary Python expressions or user-defined executable renderers.

| Draft field | Proposed initial source |
|---|---|
| subject | Session title as a proposed value for review, not an assertion that title equals legal subject |
| session_date / opening_time / location | Explicit session date/start time/location, with metadata key and snapshot value |
| organization / office | Explicit configured metadata if it exists; otherwise blank/manual |
| report_reference | Existing report number, if explicitly entered; otherwise blank according to template policy |
| referral_reference | Explicit referral input only; otherwise blank |
| investigator / clerk / statement givers | Confirmed participant roles and names; assigned session users are candidates, never automatically all investigators or signers |
| statement_blocks | Ordered included reviewed turns, preserving interruptions and unpaired statements |
| procedural_notes | Explicit evidenced/manual entries, never generated assertions |
| closing dates/times and human-only sections | Explicit human entry; no inference from upload time or last transcript segment |

The draft's `report_reference` is a document field, not the removed person reference-number system. Do not restore generated person references. Reuse UUID identity linkage.

Baseline mapping is deterministic/manual. Do not invoke the existing formal-Arabic suggestion path from this increment. Any future model-assisted mapping must be separately enabled, local-only, evidence-constrained, validated, and accepted by a human; keep it disabled by default.

### 4. Persistence and approval

Reuse the current PostgreSQL database and report draft as the session/report anchor. Proposed additive migration:

- `report_source_snapshots`: immutable source JSON, source digest/schema version, draft/session links, actor and creation time.
- `report_review_revisions`: immutable validated review JSON, source snapshot link, pinned template/mapping-policy version, revision/content digest, authenticated editor, timestamp and change summary. Unique `(draft_id, revision)`.
- `report_review_approvals`: exact revision/digest, authenticated approver/time; no client-supplied identity or timestamp.
- ReportDraft points to its current review revision. Extend GeneratedReport with optional mapping revision/export-mode and PDF path/hash metadata while retaining legacy DOCX fields and original archives.

Save one revision per explicit save/review action, not each keystroke. Require `expected_revision` for every mutation and return a conflict when another reviewer saved first. Update the revision pointer atomically and append an audit event in the same transaction. Any content, source selection, attribution, template or policy change creates a new revision with no inherited approval.

Digest input includes the source digest, template content hash/classification, mapping-policy version, fields/provenance, participant bindings, ordered turns, QA links and exclusions. Exclude approval and derived export status to avoid circular hashes. Scope approvals/downloads to the session and record.

Keep detailed evidence and changes in restricted review records. Generic operational logs contain event IDs/codes, not testimony. Existing audit infrastructure records actor/action/revision links without copying transcript text into general logs.

### 5. Arabic review workflow

Add **تعبئة النموذج من النص** beside the existing session report action; reuse the composer route with a distinct mapping mode.

1. Select recordings and the authorized or illustrative draft template.
2. Review participant bindings and roles, including unknown identities and selected-segment overrides. Changes apply to this record unless a separate existing identity workflow is explicitly used.
3. Review prefilled fields next to source quotes/metadata and timestamp/audio links.
4. Classify turns as question, answer, statement or unclassified. Explicitly confirm QA links, including multiple answers/questions. The ordered transcript remains the primary presentation so linking never duplicates or omits speech.
5. Resolve issues and inspect original versus human-corrected wording. Exclusion requires an explicit action/reason; excluded content remains auditable.
6. Review the exact revision and approve, then download DOCX/PDF. Draft downloads are available before approval with draft labelling.

Use `lang='ar'`, `dir='rtl'`, bidi isolation and text rendering. Human-only conclusions, responsibilities, proposals and closing/attestation statements remain blank until explicitly entered. Never insert assertions that an oath, reading-back, attestation or signing occurred.

### 6. Draft/approved content and template classification

Keep independent states:

- Content: draft / needs review / approved at a specific revision.
- Template: illustrative draft / explicitly authorized template.

An illustrative template always displays **مسودة غير معتمدة**, even if its content is reviewed. Reviewed content does not authorize a template. Allow a reviewed illustrative-draft download without labelling it an official issued document or bypassing existing official-finalization checks.

Template-specific requiredness controls export eligibility. Baseline reviewed export requires a subject, confirmed included attributions/roles, reviewed included turns, confirmed applicable QA links, valid evidence, no unresolved conflicts, and approval of the current revision. Name requirements are explicit policy, never invented values. Do not treat unavailable ASR confidence alone as proof of unreliability or automatically block once the relevant human review is complete.

### 7. Export path

- Generate genuine editable DOCX paragraphs/tables from the versioned review record using existing libraries and an allowlisted context. Keep flowing testimony separate from fixed-box page overlays; do not retrofit all statements into the existing raster-background designer.
- For the subsequently inspected model م ٥٣, use a first-page header and repeatable continuation-page design with a narrow right-hand margin and flowing main text. Preserve section order and margin labels, including statements, notes, conclusions, responsibilities and proposals. Do not impose the sample's three-page length on other cases or recreate the original scan as a background. The scan's answers marked س.ج do not establish missing question wording; retain only actual reviewed source questions. Details and exclusions are documented in `report-reference-review/official-form-review.md`.
- Keep uploaded authorized DOCX bytes/hash unchanged; inventory its fields/features before making a working template copy. Preserve fixed labels and document styles. Explicitly identify unsupported features instead of promising pixel-identical layout.
- Render null as blank. Distinguish unreplaced template syntax from literal testimony containing `{{ ... }}`: reject unresolved template fields without deleting or rejecting valid source quotations merely because they contain brace characters. Never render the output through a second template pass.
- Add local DOCX-to-PDF conversion in the backend runtime, preferably LibreOffice headless with suitable Arabic fonts. Use a configured executable, private temporary directories/profile, bounded time/concurrency, and a constrained process. No online converters, external relationships, macro execution or URLs from source content.
- Generate PDF from the exact DOCX artifact associated with the reviewed revision. Return a specific converter-unavailable/failed state while keeping valid DOCX export usable. Never call a PDF signed.
- Archive hashes, formats, record revision and template version. Reuse confined authenticated downloads and atomic-write/cleanup patterns.
- Check RTL paragraphs/run handling, mixed Latin `TEST-42`, digits and multi-page content structurally and visually. Native Word verification remains pending until performed in Word; current planning does not claim it passed.

## Implementation sequence and checkpoints

1. **Adapter + schema + synthetic fixtures:** exact snapshots, ordering policy, evidence validation, canonical digests. Checkpoint: all sample references validate but fixture remains ineligible for reviewed export.
2. **Persistence + mapping + API:** additive migration, revision concurrency, segment overrides, QA links, provenance, approval gates. Checkpoint: no operation mutates source transcript/speaker/identity tables; cross-session access is rejected.
3. **Review UI:** session action, source/form panels, manual roles/turns/links, issues, correction history, explicit approval. Checkpoint: two speakers, unknown identity, interruptions and one-to-many answers can be reviewed without fabricated speech.
4. **DOCX + template classification:** working draft fallback, mapped fields and flowing statements, draft/reviewed downloads. Checkpoint: original source template hash unchanged, draft banner persists, human-only sections blank, no signature integration.
5. **Local PDF + archive:** provision converter/fonts and add PDF generation/status and authorized download. Checkpoint: DOCX/PDF share the same reviewed values/turns and no text is clipped or lost.
6. **Regression and visual review:** existing report, identity and authorization tests; source-evidence invariants; Arabic/bidi and long documents; Word check explicitly recorded as passed or pending.

Suggested new modules: `schemas/report_mapping.py`, `services/report_mapping_adapter.py`, `services/report_mapping.py`, `services/report_mapping_policy.py`, `services/report_mapping_export.py`, `services/report_pdf.py`, and focused frontend components under `components/reports/`. Extend existing report API, composer, storage and archive rather than create a second app. Confirm exact endpoint names during implementation; operations should cover create/load, revisioned patch, issues, approval, draft export and reviewed export.

Pydantic and DOCX libraries are already installed. Use the available `uv` executable for any necessary Python dependency work while preserving the repository's pinned requirements and Docker build contract; do not migrate package management or introduce a separate service just for this increment.

## Acceptance cases

- Two speakers, explicit assignment, confirmed unknown name, and selected-segment correction; source speaker evidence remains unchanged.
- One question/two answers, multiple questions, interruption, unpaired statement, unanswered question; no invented pairing or duplicated/lost turns.
- Out-of-order/equal/missing timestamps and overlaps; recording-relative time is never treated as global time.
- Wrong IDs/quotes/substring offsets/timestamps; cross-session refs; duplicate IDs; unexpected input keys; clients forging reviewer/approval metadata.
- Concurrent edits, stale approval, changed template/source and refresh; manual edits preserved unless an explicit reviewed replacement is chosen.
- Missing/conflicting fields, null confidence, explicit exclusions and all configured export requirements.
- Script tags, angle brackets, ampersands, Jinja-shaped testimony, hostile instructions and URLs remain inert data with no network activity.
- Human-only sections empty by default, blank signature lines, no signing capture/services/gates.
- Exact reviewed values/turns agree across HTML form, DOCX and PDF; no leaked unresolved template tokens; persistent illustrative-draft banner.
- Arabic, English IDs, Arabic/Western digits, punctuation and long multi-page text; authorization on every artifact; conversion failure leaves DOCX usable.

## Open items, not blockers to the baseline

- No authorized current blank DOCX is included. The supplied historical PDF now permits a reconstructed model م ٥٣ layout for review alongside the generic draft. Keep reconstruction status explicit until the organisation accepts the template; an original blank DOCX would improve fidelity but is not a prerequisite to building a reviewable reconstruction.
- No local DOCX converter is installed in the backend: provision and verify it during PDF phase; valid DOCX output must remain independently usable.
- The bundle leaves name-required policy configurable. Proposed baseline permits a deliberately confirmed unknown name, while requiring reviewed attribution and role; present that policy clearly before implementing reviewed export.
- Physical printed layout must be checked in the organisation's Word environment before claiming native Word fidelity.

No production records, templates, authentication settings or application code were changed in this planning step.
