# PDF preview and paragraph flow — 2026-10-27

The live PDF endpoint returned HTTP 200, while the application's CSP omitted a
frame-src directive permitting the blob URL used by the preview iframe. Added
`frame-src 'self' blob:` and a separate-window PDF link with visible loading state
and PDF response validation. Other CSP restrictions remain in place.

Printed narrative text now justifies within the existing ruled writing column.
Single line breaks flow as spaces; blank lines retain paragraph separation.
The renderer escapes text before introducing paragraph breaks. Stored report text
and issued files are unchanged. Headings and signatures retain their alignment;
page dimensions, column widths, margins and fixed wording were not changed by
this fix. The scanned reference remains the layout target, not a claim of exact
font or pixel equivalence.

Verification: 8 focused backend tests passed; frontend production build passed;
nginx configuration passed. Synthetic short and long PDFs rendered successfully
(1 and 14 pages); the short PDF was visually compared with reference page 12.
Live verification returned a valid 354333-byte PDF, confirmed the blob-frame CSP,
healthy release images and byte-identical frontend assets. The draft revision
was unchanged. Embedded browser display was not directly verified because the
native browser connection was unavailable.

Deployment retained database/storage backups and rollback images under
`storage/backups/report-opening-20261027T081721Z/`. Evidence is recorded in
`storage/test-artifacts/report-opening/pdf-preview-runtime.json`.
