# Interviewed person (بيانات الشخص)

How the system records **who was interviewed**, their identity documents, and the scans of
those documents.

## Design rule

An investigation must always be recordable, even when the person cannot or will not
identify themselves. Every field here is optional, and "غير محدد الهوية" / "لا يحمل وثائق
ثبوتية" are first-class states — not error conditions.

## The cascade

```
نوع الشخص:   ( ) مدني        ( ) عسكري        ( ) غير محدد الهوية
   │
   ├─ عسكري   → الجهاز (الجيش / قوى الأمن الداخلي / الأمن العام / أمن الدولة / الجمارك / آخر)
   │             الرتبة · الرقم العسكري · الوحدة · القسم
   │
   ├─ مدني    → الجنسية ▾  (لبناني أولاً، ثم سوري/فلسطيني/عراقي… — قائمة عربية مضمّنة، بدون إنترنت)
   │      ├─ لبناني      → رقم السجل · محل القيد (قضاء/بلدة) · ☐ مكتوم القيد
   │      └─ غير لبناني  → بلد الجنسية (الوثائق تحدّد الباقي)
   │
   └─ غير محدد → ☑ لا يحمل وثائق ثبوتية (تلقائياً) + سبب عدم توفر الوثائق

مستوى التحقق من الهوية:  إفادة الشخص · شوهدت الوثيقة · تم التحقق رسمياً
```

`مستوى التحقق` matters legally: it distinguishes a name the person merely *stated* from one
where the investigator *saw* a document, from one *verified* against a registry.

## Documents are a list, not a single field

A person routinely carries more than one document — a Lebanese national with an ID **and**
a passport, a Syrian with a passport **and** a UNHCR card, someone with an expired passport
**and** a residency permit. So `subject_documents` is a 0..n table, each row optionally
carrying one scan.

The **type list follows the branch**, but storage is uniform:

| Branch | Offered types |
|---|---|
| Lebanese | بطاقة هوية · إخراج قيد · جواز سفر · رخصة سوق · وثيقة أخرى |
| non-Lebanese | جواز سفر · إقامة · بطاقة المفوضية (UNHCR) · بطاقة الأونروا (UNRWA) · وثيقة سفر للاجئين · رخصة سوق · وثيقة أخرى |
| military | بطاقة عسكرية · بطاقة هوية · إخراج قيد · جواز سفر · وثيقة أخرى |

Each document holds: type, number, issuing country, issue/expiry date, notes. Expired
documents are flagged automatically (`is_expired`).

## Lebanon specifics

* **رقم السجل + محل القيد** are captured separately from the ID-card number — for Lebanese
  nationals the civil-registry entry, not the card, is the authoritative identifier.
* **مكتوم القيد** (unregistered Lebanese) is an explicit flag, because such a person has no
  registry number at all and would otherwise look like missing data.
* Refugee document types (UNHCR / UNRWA / refugee travel document / residency permit) are
  first-class rather than lumped into "other".

## Document scans are treated as evidence

Uploading is optional. When a scan is attached it is handled like the audio originals:

* **JPEG / PNG / WEBP / PDF only**, verified by **magic bytes** — a `.exe` renamed to
  `.png` is rejected;
* 20 MiB cap, streamed to disk, stored at
  `storage/subject-documents/{session}/{document}.{ext}` with the path resolved inside the
  storage root;
* **SHA-256 recorded, original never modified**;
* re-uploading over an existing scan returns **409** — replacing evidence requires an
  explicit delete first;
* **PDFs are always served as `attachment`**, never rendered inline; images are served
  `inline` with `nosniff` and `no-store`;
* the frontend fetches through an authenticated request and opens an object URL, so the
  access token never appears in a URL, browser history or proxy log.

### Who can see a scan

A dedicated permission, **`subjects.documents.view`** (ADMIN + INVESTIGATOR), *in addition
to* access to the session. Being able to read a transcript does not expose someone's ID
photo, and the read-only USER role never sees scans. Uploading or deleting additionally
requires `investigations.update`.

Every upload, view and deletion is audited (`SUBJECT_DOCUMENT_UPLOADED` / `_VIEWED` /
`_DELETED`) with the document type and SHA-256 — never the file content.

## Duplicate detection

If a document number already appears in another session, the subject shows
`duplicate_of_sessions` with those session numbers. This **warns, never blocks** — the same
person legitimately appears in several investigations, and the investigator decides what it
means.

## API

```
POST/PUT /api/investigations/{id}                     subjects[] with documents[]
POST     /api/investigations/{id}/subject-documents/{doc_id}/file    upload a scan
GET      /api/investigations/{id}/subject-documents/{doc_id}/file    download it
DELETE   /api/investigations/{id}/subject-documents/{doc_id}/file    remove it
```

Editing a session preserves already-uploaded scans: documents are matched by `id`, so
renaming a subject or adding a document never orphans a file. Removing a document from the
list deletes its scan from disk.

## Notes for deployment

* The nationality list is bundled offline (`central/frontend/src/lib/countries.ts`),
  Lebanon first, then the nationalities most frequently encountered locally.
* Consider a retention policy for scans — they are the most privacy-sensitive data the
  system holds. The storage layout (one directory per session) makes per-session deletion
  straightforward.
