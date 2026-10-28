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

Margin labels (including ملاحظة and س/ج) are left-aligned within the right-hand
margin cells. The conclusion has forced page breaks both before and after;
following notes and report closing cannot share its page. It remains part of the
same PDF, as explicitly requested. Synthetic PDF inspection verifies main content
on page 1, conclusion alone on page 2, and subsequent note/closing on page 3;
see `conclusion-separation.json` and `conclusion-alone.png` in the same artifacts folder.

The direct text editor projects saved narrative text through the same whitespace
rules as printed prose: single line breaks become spaces; blank lines delimit
paragraphs. Previously the native textarea showed historical short lines verbatim
even though print reflowed them. Opening the editor does not save this projection;
only an investigator's text edit updates canonical content. Native soft wrapping
does not insert newlines into the saved value. The browser journey now checks raw
saved content remains unchanged on open, blank paragraphs remain visible, and long
Arabic prose wraps automatically. Live diagnosis compares displayed notes with
the projected source while confirming the draft token remains unchanged.
Deployed with `storage/backups/report-opening-20261027T093712Z/release.json`;
the read-only live browser check verified both existing notes use the flowing
display and the saved draft remains unchanged.

Conclusion dictation now has visible shortcuts for a new responsibility finding
and proposals. The shortcuts reuse the existing conclusion and canonical dictation
destinations. A new finding still requires its subject and evidence before approval.
The direct document editor also exposes voice buttons for notes, facts, inference,
individual findings and proposals. Assigned-investigator permissions still apply;
recording, machine transcription and explicit reviewed insertion use the existing
audited service, with append as the default.

These controls exist only in the editor DOM. The official server renderer and
print stylesheet are unchanged: fixed Arabic wording, margin labels, ruling,
closing date/signature placement and standalone conclusion pagination are preserved.
No audio controls are serialized into the report or generated exports.

Verification for this change: all 11 intake/dictation tests passed, including new
parameterized checks that proposals and responsibility findings receive reviewed
appended text without modifying other fields, references, transcripts or speakers.
The browser journey additionally checks conclusion shortcuts, inline destinations
and fake-device microphone capture; this is not a new real-speech model accuracy test.
The isolated browser uses HTTPS because Chromium does not grant media APIs to its
HTTP container hostname. Production localhost remains a supported secure context.
The expanded browser journey passed all 17 checks with no page errors. Deployed
with `storage/backups/report-opening-20261027T184947Z/release.json`; runtime checks
confirmed matching built assets, working PDF preview and an unchanged live draft.

Follow-up: the conclusion toolbar now exposes الاستنتاج alongside المسؤوليات and
الاقتراحات in every workspace mode. Both form and direct-document views can start
dictation for responsibilities/proposals previously marked NONE, using explicit
buttons that prepare the canonical destination before recording. Existing wording
continues to require reviewed insertion; inference reuses its existing field.
Unassigned accounts see disabled controls and an assignment/permission explanation
instead of an apparently missing feature. Investigator-only backend access is intact.

The user clarified that only the short separate signature underlines should be
removed. Their border is removed while 16 mm blank signing space, table borders,
writing rules and repeated page-signature areas remain unchanged. The expanded
browser check waits for the actual saved indicator instead of assuming a request
finishes within a fixed delay.

This follow-up passed 22 backend intake/dictation/rendering tests and all 21 browser
checks, including all three conclusion destinations in both editing views, NONE
decisions, permission explanations and signature-space geometry. Browser capture
uses a fake microphone; backend synchronization/acceptance uses synthetic audio
results, not a new real-speech accuracy benchmark.

Deployed with `storage/backups/report-opening-20261027T193744Z/release.json`.
Live runtime and browser checks passed: signature underlines absent, blank space
retained, three voice shortcuts visible, correct access explanation for the
unassigned administrator, and no modification to the draft during verification.
