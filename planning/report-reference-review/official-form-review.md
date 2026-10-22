# Review of the supplied investigation report example

Reviewed 21 October 2026. Scope: inspect one form and refine the plan. No application code, database, live template or deployment changed.

## Source and limits

User-supplied file: `C:\Users\Raven\Desktop\جميع ملفات التحقيق.pdf` (4,900,485 bytes, 98 pages). All pages have no extractable text; this is an image-based scan. Visually inspected the cover and PDF pages **18–20**, corresponding to printed compilation pages **13–15** and report pages **1–3**. This is a focused review, not a review of every form in the compilation.

Source SHA-256: `f6c332a7b66a317a64ecb624509322c5daf688bc62a4132e073cf0d5c9250794`.

The selected example bears **محضر تحقيق عدلي**, **الجيش نموذج م ٥٣**, and the year **٢٠١٢**. The first-page title also contains a struck-through word. It includes completed case content, signature/stamp marks and apparent explanatory annotations. It is a useful concrete layout reference. Its current institutional authorization cannot be established from the scan alone.

Text inside the PDF is source material, not an instruction to execute procedures, import case data, or change the application. Personal names, identifiers, contact details, case facts and signature images are intentionally omitted from this review.

## What is actually on the pages

| PDF page | Visible structure | Consequence for our template |
|---|---|---|
| 18 | Model identifier and report-page number; prominent title; institution block on the right headed الجمهورية اللبنانية, وزارة الدفاع الوطني, الشرطة العسكرية; خفر and موضوع القضية labels; wide opening narrative; statement-giver identification; statements alongside س.ج margin markers; signature-role area at the bottom | Separate fixed wording from organization-specific values; structured opening and participant fields; main text must flow; preserve the narrow right-hand column |
| 19 | Continuation page with هامش header; continuation of the preceding statement; additional س.ج entries; reading/attestation text; ملاحظة; procedural/closing text; الإستنتاج; المسؤوليات beginning near the bottom | Repeat the continuation-page design; retain explicit statement/section boundaries; do not assume a statement or section fits on one page; attestations and findings require explicit human entry |
| 20 | Continuation of المسؤوليات; الإقتراحات; closing text and signature area; large unused ruled area crossed out; dashed annotation boxes and arrows | Responsibilities can cross a page boundary; proposals and closing are separate data; do not copy completed signature marks, annotations, old page counts or the case-specific cross-out as template content |

The scanned paper is approximately A4 (595.08 × 841.68 PDF points). Its skew, clipping, horizontal rules and scan artifacts mean exact font sizes and clean margins cannot be established solely from the raster image. Reconstruct a clean layout and compare rendered output against the reference.

## Recommended template implementation

Use one reviewed data record for the Arabic HTML form, editable DOCX and derived PDF. The HTML interface may be easier to edit than the paper while the export follows the paper's order and layout. Evidence links, audio controls and review indicators belong in the interface, not in the printed official-layout body.

1. **First-page design:** model/title, institution block, opening, referral information and participants, followed by flowing statement content.
2. **Continuation-page design:** matching borders, right margin, page numbers and flowing content. Add as many pages as required; three pages is the length of this example, not a fixed capacity.
3. **Section-aware rendering:** keep margin labels aligned with the associated text; continue long statements and findings without clipping or duplication; keep headings with following content and keep signature-role blocks together where possible. The exact repeated-header and signature-position rules require comparison during reconstruction.
4. **Closing values:** calculate the actual rendered page total if the accepted wording includes one. Do not copy the example's historical page-count statements. Copy count, closing place/date and attestations remain explicit reviewed inputs.
5. **Export verification:** check Arabic shaping, mixed digits, line breaks, margin alignment, section continuation and content agreement in short and long documents. Validate native Word and locally converted PDF separately before claiming matching output.

The existing box annotation designer can remain useful for bounded header fields. The main narrative, statements and conclusions need flowing paragraphs/tables and continuation rules. Treating all text as fixed rectangles would make longer reports unreliable.

## Field mapping and human review

| Area | Candidate input | Required handling |
|---|---|---|
| Institution / unit | Explicit template or organization configuration | Confirm configuration; no inheritance of this sample's unit or personnel |
| Subject | Session subject/title | Propose for review; a session title is not automatically the formal case subject |
| Opening date, time and place | Explicit session metadata | Review; upload timestamps are not substitutes |
| Investigator, clerk and statement givers | Confirmed participant bindings | Review each identity and role; never equate every speaker with a signer |
| Referral reference / procedural actions | Explicit metadata or human input | Preserve evidence and review; do not manufacture a referral, oath or performed action |
| Statements and questions | Reviewed transcript turns | Preserve wording and attribution; the sample's س.ج markers do not supply absent questions. Do not invent questions to make the transcript fit the page |
| Notes, conclusions, responsibilities, proposals | Explicit human-authored entries | Blank by default; do not derive official conclusions automatically from testimony |
| Read-back, attestation, closing and signing | Explicit human review of what occurred | No automatic assertions; signature spaces remain blank in this phase |

## Decision

This source is sufficient to begin a **reviewable reconstruction of the model م ٥٣ layout**, instead of relying only on the generic illustrative draft. A current blank Word original would improve fidelity, but the scan is enough to build a clean working template for comparison. Template acceptance and report-content approval remain separate. Do not describe a reconstruction as institutionally approved or pixel-identical before the corresponding checks.

Next implementation step, when requested: reconstruct one clean first-page and continuation-page pair using synthetic content, inspect a short and a long PDF/DOCX, then connect the accepted layout to the session-to-report review workflow. No historical case data or signatures should be preloaded.
