# Direct report editing and formal ending

The military command-desk design continues (DFII 14): navy/olive controls around
white ruled document pages, retaining IBM Plex Sans Arabic and Inter. The main
action is **تحرير المحضر قبل الطباعة**. Native text areas inside the server-rendered
document edit the canonical statement question/answer, note, conclusion and
responsibility fields. Official wording, identities, references and signatures
remain protected. Templated notes retain their variable-based editing controls.

Inputs update the same revision-checked autosave queue as the form editor. The
document frame does not reload while typing. Failed saves retain text, retry is
explicit, and conflict reconciliation includes closing text. Issued documents
remain read-only; correction uses the existing successor workflow.

The opening margin no longer repeats the case subject. The subject remains in
the opening narrative. Following the user's clarification, paired questions and
answers retain margin س/ج and س: / ج: labels. The س/ج margin marker also remains
beside standalone testimony, even without a question. Standalone testimony and
identity details have no stray ج: prefix. Responsibility and proposal shortcuts open the existing single
conclusion, preserving its people/evidence links and deliberate none decisions.

**ختام المحضر** adds an optional, editable closing paragraph, place and date,
followed by assigned clerk/investigator names and empty signature spaces. It
appears after all blocks, including notes after the conclusion. The reference
image supplies structure only; no scanned names, signatures, stamps or claimed
page/copy counts are copied. The closing group stays together where it fits.
An enabled but incomplete closing blocks issuance. Existing drafts need no data
migration; the optional typed JSON object is audited with the existing before/
after report snapshots. Existing issued files and hashes are untouched.

Verification: 34 backend report/integrated workflow tests passed, plus 9 focused
renderer/opening tests (overlapping coverage, not 43 distinct tests). Production
frontend build passed. A real Playwright browser journey against isolated services
passed direct editing, autosave during typing, failed-save/retry, closing persistence,
PDF download, conclusion navigation and mobile editor visibility without page errors.
Synthetic short/long PDFs (2/15 pages including the closing) were generated and the
end pages inspected. The closing and signature arrangement follow the reference;
the scan's unidentified typeface and exact pagination are not reproduced.

The follow-up live read-only diagnosis found an editable draft, ready intake,
seven enabled narrative fields and no browser errors using the authorized
verification account. The protected opening precedes the fields. The editor now
shows the editable-field count, first-field navigation, a field selector,
top/bottom controls, explicit refresh, and visible horizontal/vertical scrolling.
A4 proportions are retained on narrow screens, with horizontal scrolling rather
than squeezed Arabic columns. Preview refresh preserves both scroll positions.

Evidence: `storage/test-artifacts/document-editor/`. Deployment manifest and
rollback images: `storage/backups/report-opening-20261027T084811Z/release.json`.

Scrolling/Q&A follow-up deployed with manifest
`storage/backups/report-opening-20261027T090032Z/release.json`. Nine focused backend
tests and the expanded browser journey passed, including both scroll axes, first
field focus and refresh persistence. A read-only browser check on the actual
target report confirmed seven enabled inputs, successful field navigation,
enabled scrollbars and no browser errors. The draft token remained unchanged.

The subsequent margin-marker correction was deployed with
`storage/backups/report-opening-20261027T091607Z/release.json`. Live browser
verification confirmed three statement-entry margin cells containing س/ج,
including entries without questions. No testimony was entered or changed.

Closing date positioning corrected in release
`storage/backups/report-opening-20261027T092418Z/release.json`: place/date sits
in the left signature area above the investigator, beside the clerk's area.
ISO date storage remains unchanged; print displays DD/MM/YYYY in an LTR-isolated
element. Chromium geometry assertions and inspected short/long PDF rendering
verify alignment and prevent RTL reordering. Evidence:
`storage/test-artifacts/report-opening/closing-date-layout.json` and `date-position.png`.
