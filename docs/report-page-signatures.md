# Signing space on continued report pages

Reference reviewed: `جميع ملفات التحقيق.pdf` (98 pages), PDF pages 34–35,
55, 73 and 82. These are PDF page numbers, not the numbers printed on the scans.

- Pages 34–35: continued and final conclusion pages carry investigator signing.
- Page 55: complete statements retain their individual signing groups; a continued
  statement also has person/clerk/investigator labels at the page bottom.
- Page 73: a note uses clerk/investigator signing rather than the interviewee.
- Page 82: conclusion and subsequent notes retain their individual endings and
  investigator signing. No scanned signature, stamp or personal fact is reused.

Implementation uses a `tfoot` owned by each report section's ruled table. Chromium
reserves the footer's height and repeats it on continued pages. The final footer
is the section's existing signature block, so no additional final copy is inserted.
The opening still flows into the first section; subsequent tables keep section
ownership so one person's signature role cannot leak into a later person's page.
An opening-only draft also has a signing footer. Signing space is 16 mm minimum,
and the signature baselines align despite different name lengths. The clerk and
investigator keep their canonical names; no new signing confirmation is inferred.

The formal headings, fixed clauses, margin column, left-aligned margin labels,
statement Q/A markers, text order and standalone conclusion remain. Digital
continuation signing areas stay within the ruled table; the scan's handwritten
stamps sometimes extend outside its border. This is not a claim of pixel identity
to the scanned paper. Existing issued HTML/PDF files remain immutable; the renderer
digest automatically invalidates old draft review confirmations.

Verification artifacts: `storage/test-artifacts/page-signatures/`. Seven synthetic
documents cover short/long statements, long notes, long conclusions, mixed sections
and opening-only drafts, including two different people with continued statements.
PDF extraction checks each continued statement retains its own person's signing
label, every page has signing labels,
body tokens remain complete and unique, and no body token runs below the final
signature area. A single-section final page has one signature group. Reference and
generated pages were visually inspected. Browser editing, dictation and autosave
regressions remain necessary because report sections now use individual footers.

Validation passed: 36 report/workflow tests; all 17 isolated browser checks;
54 pages across the seven synthetic PDFs. The established three-page separation
fixture still places main content on page 1, conclusion on page 2, and subsequent
note/closing on page 3. Closing-date geometry assertions also passed.

Deployed with `storage/backups/report-opening-20261027T191024Z/release.json`.
Live runtime verification passed with matching frontend assets and unchanged draft
revision. All four pages of the actual draft preview were inspected, including
signing areas, margin/Q&A labels and standalone conclusion. The draft's missing
clerk/signing details remain explicit placeholders; no investigator facts were
invented. Internal preview artifact: `storage/test-artifacts/report-opening/runtime-preview.pdf`.
