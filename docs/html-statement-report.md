# Repeatable HTML إفادة and ملاحظة blocks

The session report page opens the HTML editor. Add an إفادة, select a session
speaker or fill it manually, complete the marked variables, and add answer rows.
Add a ملاحظة for a separate action or decision. All blocks have independent values
and IDs and can be interleaved in any order, for example إفادة → ملاحظة → إفادة →
ملاحظة. Blocks can be reordered or removed; the last removed block can be restored
before leaving the editor.
The topic and responsible investigator are shown above the blocks. Investigators
are selected from the session's assignments.

The first block type follows the supplied statement scan: a right-hand س.ج column,
ruled text, identity paragraph, optional verification/attestation clauses and
signature spaces. Its 21 variables are defined in
`central/backend/app/assets/html_statement.json`. Example names, numbers, answers,
family status and prior-record assertions from the image are not default values.
The verification and attestation sentences are opt-in factual clauses.

The second supplied scan defines the ملاحظة block. It has a right-hand ملاحظة:
column, ruled narrative and two signature areas. Its seven variables are defined
in `central/backend/app/assets/html_note.json`:

- `note_date` and `note_time`: date and time of the recorded action.
- `note_text`: the complete editable narrative, including any consultation,
  contacted person, decision, requested examination or closing wording.
- `closing_location` and `closing_date`: place and date of preparation/signing.
- `clerk_name` and `investigator_name`: the clerk and investigator's names/ranks.

Each new note starts blank. Names, dates and the firearm/expert request in the scan
are not default report facts. The responsible session investigator is used for a
blank investigator signature field; a block can explicitly override its signer.
Notes are authored report text, not speaker answers, and have no transcript-source
or speaker fields. Adding a note does not request model inference.

The document renderer is `central/frontend/src/lib/html-report.ts`; alignment,
ruled lines, margins, type size and A4 print styles are in the adjacent
`html-report.css`. HTML downloads embed the local Noto Naskh Arabic font, its OFL
license, and CSS. No remote fonts, scripts, models or services are required.
The editor offers HTML download and browser print/save-as-PDF after saving.

This is a saved HTML **draft/export** workflow. The existing Word/M53 issuance
and immutable archive remain accessible through the previous-templates button.
The HTML draft is stored as `official_form.html_report` on the existing
session-owned report draft; no schema migration is required. Both editors preserve
the other's values. The schema accepts a discriminated `statement | note` union.
The existing `statement-html-1` document revision is retained as an additive
extension so saved statement-only documents need no migration.

API:

- `GET /api/report-forms/html-statement`: statement catalogue and wording, with
  the note catalogue in the additive `note` property.
- `POST /api/investigations/{session_id}/report/html`: idempotent draft creation,
  including manual reports before audio exists.
- `GET/PUT /api/investigations/{session_id}/report/html`: load/save with content-token
  conflict detection, a database row lock, session permissions and auditing.

Answers can be imported for the selected speaker. The server checks every source
block belongs to the draft and that its answer belongs to that speaker, then copies
source text, segment IDs, recording IDs and timestamps into a snapshot. The snapshot
survives subsequent legacy-QA refresh. Client-provided snapshots are rejected.
HTML text is escaped, with a restrictive document CSP. Finalized drafts cannot be
edited. Payload limits are 500 total blocks, 500 answer rows per statement and a
two-million-character document bound; these are operational limits, not one-person
template restrictions. Note text is limited to 40,000 characters. No report action
changes the source transcript.

Initial statement validation and rollout:

- 43 distinct backend tests passed across HTML API, existing report API, M53 and
  draft suites, using only the isolated `_test` database. This includes source
  fingerprints, session isolation, concurrent-edit rejection, manual creation,
  multiple statements, legacy coexistence and retained source snapshots.
- Ten frontend checks passed, including all 21 placeholder variables, repeated
  statements, Arabic text preservation, escaping, source times and transcript
  grouping. TypeScript and the production frontend build passed.
- No browser surface was available through CUA, so interactive visual alignment
  and the browser print dialog were not verified. The blank HTML artifact generated
  by the actual renderer is at
  `storage/model-evaluation/results/html-statement/blank-mask.html`.
- The supplied live session remained a draft with 19 existing QA blocks; the
  verification transaction was read-only. Its HTML section starts empty for the
  operator to populate. Live page, JS/CSS/font byte hashes, backend/database health
  and the unauthenticated catalogue's HTTP 401 response were checked.
- Deployed tags: `military-stt/central-backend:html-statements-20261024` and
  `military-stt/central-frontend:html-statements-20261024`, also tagged `1.0.0`.
  Both prior images are retained as `before-html-statements-20261024`.

Backend image ID: `sha256:b070978062054b29d00fdee48d56efda98afa1f53d01472d81db8408b7d44910`.
Frontend image ID: `sha256:fe4a79b838ad3c7fb805a0f8824a0e44e6b0eaebbea21fbf452609feb68a7c5a`.

Note extension review artifacts (generated by the production renderer with the
embedded local font and CSS):

- `storage/model-evaluation/results/html-statement/blank-note-mask.html`
- `storage/model-evaluation/results/html-statement/mixed-report-mask.html`

The note tests cover mixed ordering, note-only reports, independent fields,
removal/restoration, old statement documents, legacy coexistence, server source
snapshots, duplicate IDs, unknown fields/types, payload bounds and HTML escaping.
No browser surface was available through CUA for visual print verification.

Note extension validation and rollout (2026-10-24):

- All nine HTML report backend tests passed against the isolated `_test` database.
- Both frontend HTML renderer tests and the TypeScript/production build passed.
- Live JS/CSS hashes match the build; `/api/health` reports a healthy database.
  The catalogue still returns HTTP 401 without authentication. The running backend
  reports 21 statement fields and seven note fields and accepts a note-only schema.
- Deployed tags: `military-stt/central-backend:html-notes-20261024` and
  `military-stt/central-frontend:html-notes-20261024`, also tagged `1.0.0`.
  Previous images are retained as `before-html-notes-20261024`.
- Backend image: `sha256:673d323af4c2d2fa9b2b8fda6de3b16babc4d0502e14e8fc61bac93423f92ef4`.
- Frontend image: `sha256:8fb68a2a284ab8ff0b7b2df3722cf4caaafe4d4bf22fc92ff9baa2c246195413`.
