# Official report reference and fixed wording

Reference: the user's local `جميع ملفات التحقيق.pdf` (98 scanned pages). Page numbers below
are PDF page positions, not the printed archival folio numbers. Scans are reference material;
their incident facts, names, handwritten signatures, stamps, and scan artifacts are not templates.

| Reusable family | Representative pages | Reused structure |
|---|---|---|
| Judicial investigation statements | 55, 73 | Heading naming the person; identity declaration; س.ج markers; attestation; interviewee/clerk/investigator signature arrangement |
| Procedural notes | 73, 82 | هامش marker ملاحظة:; free procedural narrative; optional action date/time; separate closing/signature line |
| Investigation conclusion | 34–35, 82 | خلاصة تحقيق عدلي; الوقائع، الاستنتاج، المسؤوليات، الاقتراحات; lead investigator signature |
| Specialized reports and annexes | Other scanned case-file pages | Reference only in this phase; not selectable as new report formats |

Blank wording transcribed from the inspected statement examples:

- `إفادة {statement_rank} {statement_name} رقم {statement_service_number}` (p. 55; rank/name/number are variables).
- `تأكدنا من {identity_documents} وأعيدت إليه.` (pp. 55, 73; the document description is variable).
- `تليت عليه إفادته فصدقها ووقعها بحضورنا نحن والكاتب العدلي.` (pp. 55, 73).
- `خلاصة تحقيق عدلي` and `الوقائع` / `الاستنتاج` / `المسؤوليات` / `الاقتراحات` (pp. 34–35, 82).
- `لا يوجد` is a deliberate conclusion decision, not a default substituted for an unanswered field (p. 82).

The template locks these words in server assets/renderer code. Browser and dictation APIs accept
typed variable values only; fields such as `attestation` are invalid dictation destinations.
Verification and attestation clauses require a later explicit confirmation of the actual action.

The editable schema revision is `investigation-html-2`. Historical `statement-html-1` artifacts
are downloaded and verified from their original stored bytes. New review tokens include the
renderer/assets digest. A renderer change invalidates draft approval without changing issued files.

Layout implementation uses A4 pages, ruled text, a narrow right هامش column, repeated table
headers, and kept-together signature groups. Conclusions start on a new page; later notes remain
in document order. Inter and IBM Plex Sans Arabic are bundled. HTML and PDF share the server
renderer; PDF uses the pinned Chromium supplied with Playwright 1.55.0.

Visual comparison and long-document pagination evidence are recorded under
`storage/test-artifacts/complete-workflow`. The seven-page synthetic report was visually checked
for Arabic readability, repeated headings, conclusion page start, subsequent notes, signatures,
and clipping. The release verification record distinguishes completed checks from pending ones.
