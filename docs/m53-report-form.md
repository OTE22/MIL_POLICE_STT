# Structured M53 report

Open **قالب المحضر** to preview the built-in blank form. In a session's report composer,
choose **م ٥٣ — النموذج المسطّر بصياغة المصدر**, then save the selection and values.
Use **ملء الحقول الفارغة من بيانات الجلسة** to copy available session facts without replacing
entered values. Unknown personal details and decisions must be entered and reviewed.

The source's opening prose, first-person identity paragraph, note, findings,
responsibilities, proposals, signature spaces and ruled continuation pages are retained.
There are 55 entered variables and one automatically calculated total-page count.
The PDF begins with the source's three-page structure and adds pages when necessary.
The archived PDF is the print master; Word is an editable copy with embedded Arabic fonts.
Reconstruction from a skewed scan does not establish
pixel identity or institutional approval.

Save values first. Then review the Q&A and confirm the procedural facts that actually
occurred. Unconfirmed procedural sentences are omitted, while their section labels remain.
Saving a confirmation records the authenticated user, UTC time and exact content digest.
Changing values, Q&A, attribution or selected source invalidates the review. Finalization
also refuses stale transcripts and ambiguous/unknown answer attribution. This version of
the built-in form supports one identified statement-giver per report; the existing Word
template workflow remains available for other layouts.

Issuing creates an immutable Word file, PDF, context snapshot and database archive row.
PDF and Word downloads share session authorization and audit logging. Integrity checks
cover both output files and the snapshot. Recorded confirmations and hashes are not a
certificate-based digital signature. The form does not manufacture signature marks.

Migration `f0a6b4e13d82` only adds nullable fields. Older drafts and issued Word reports
remain readable. Server rendering is local, uses pinned Python dependencies and embedded
open-license fonts, and does not require Office, LibreOffice, a browser service or a cloud API.

Verification includes the report regression suite plus `tests/test_report_m53.py`: character
preservation over multiple pages, long tokens and mixed Arabic/Latin text, unsupported
glyph rejection, permission checks, conflict handling, review invalidation, archive and
download integrity, and unchanged source evidence. Reproducible fictional review artifacts
are generated with `planning/report-template-m53/build_runtime_samples.py`.
