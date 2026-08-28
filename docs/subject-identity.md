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
   ├─ عسكري   → الجهاز * (الجيش / قوى الأمن الداخلي / الأمن العام / أمن الدولة / الجمارك)
   │             الرقم العسكري * · الرتبة · الوحدة · القسم
   │
   ├─ مدني    → الجنسية ▾  (لبناني أولاً، ثم سوري/فلسطيني/عراقي… — قائمة عربية مضمّنة، بدون إنترنت)
   │      ├─ لبناني      → رقم السجل · القضاء · البلدة · ☐ مكتوم القيد
   │      └─ غير لبناني  → بلد الجنسية (الوثائق تحدّد الباقي)
   │
   └─ غير محدد → ☑ لا يحمل وثائق ثبوتية (تلقائياً) + سبب عدم توفر الوثائق

   * مطلوب: الجهاز + الرقم العسكري معاً يُنتجان الرقم المرجعي MIL-<الجهاز>-<الرقم>.
     «آخر» مرفوض: تصنيف جامع لا يصلح مساحةَ أسماء. وجندي لا يُعرف رقمه يبقى قابلاً
     للتسجيل بلا رقم مرجعي — أما رقمٌ بلا جهاز فمرفوض.

مستوى التحقق من الهوية:  إفادة الشخص · شوهدت الوثيقة · تم التحقق رسمياً
```

`مستوى التحقق` matters legally: it distinguishes a name the person merely *stated* from one
where the investigator *saw* a document, from one *verified* against a registry.

## الرقم المرجعي — derived, not typed

الرقم المرجعي is the **canonical identity key**: it is what ties one person together across
sessions, and what voice prints are grouped by. It used to be the only identity field typed by
hand, so the same soldier arrived as `MIL-4471`, `MIL 4471` and `4471` — three canonical
people, and a voice matcher that treated one person's own prints as rivals.

It is now **derived from identifiers the operator has already entered**, and shown in the form
marked *مشتق تلقائياً*.

### Derived, or issued — never guessed

Only one thing is derived from paperwork, because only one identifier has a proven
person-unique namespace. Everyone else is **issued** a reference by the system.

| Person | Reference | Where it comes from |
|---|---|---|
| عسكري | `MIL-ARMY-4471` | **Derived** from الجهاز + الرقم العسكري. A serial is unique **within its force**: Army 4471 and ISF 4471 are two people, so الجهاز is part of the key. `آخر` is a catch-all, not a namespace — it derives nothing. |
| مدني (any) | `CIV-00000145` | **Issued** from a sequence. Lebanese or foreign, refugee or resident, documented or not. |
| غير محدد الهوية | `TMP-2026-000123` | **Issued** — a placeholder for someone not yet classified. |
| عسكري بلا رقم عسكري | **nothing** | Neither derivable nor classifiable as a civilian. |

### رقم السجل identifies a family, not a person

This is why civilians are issued a reference rather than keyed on their civil record.

An **إخراج قيد** lists everyone registered under one رقم سجل — it is a household record. The
system once derived `LBN-<قضاء>-<رقم السجل>` from it, which gave a father, his wife and his
children **one canonical identity**. That failed in two ways:

* relatives with **different names** were refused outright — the second one could not be
  recorded at all, because the reference was already registered under someone else;
* relatives with the **same name** were merged silently, and naming a son after his
  grandfather is ordinary here. Their voice prints then pooled onto one person.

The second is the dangerous one, and it is invisible to any name-based check. So القضاء and
رقم السجل are now **metadata**: recorded, searchable, and identifying nobody.

> An extra identity awaiting consolidation is recoverable. Two humans merged into one
> biometric identity is not.

محل القيد is still chosen from the 26 أقضية and stored as a validated code, because it is
useful for finding people — it simply no longer keys anyone.

### Investigators are people too

Anyone who **speaks** in a recording needs to be identifiable, and the investigator asking the
questions speaks in every one they run. So an investigator is a row in the same
`person_identities` registry as the people they interview — not a separate kind of record.

They are registered under the **military rule, unchanged**: `MIL-<BRANCH>-<الرقم العسكري>`, using
the same `derive_reference` that serves subjects. `الجهاز` and `الرقم العسكري` are therefore
**mandatory on every user account**, and `آخر` is refused for the same reason it is refused for
a subject — it is a catch-all, not a namespace.

Registration happens when they are **assigned to a session**, not when the account is created:
that is the first moment they could appear in a recording, and it keeps accounts that never sit
in an interview out of the registry.

### External identifiers find a person; they are not the person

A passport, an UNHCR card or a residency permit is **evidence**. It helps locate an existing
canonical person so the same human is reused across investigations instead of entered twice —
and it can be reissued, corrected or replaced without that person becoming someone else.

Only a namespace proven person-unique may resolve an identity automatically:

| Identifier | Namespace | Resolves? |
|---|---|---|
| بطاقة المفوضية / الأونروا | the agency itself | yes |
| جواز سفر · إقامة | the **issuing country**, which must be supplied | yes, with the issuer |
| بطاقة هوية · إخراج قيد · رخصة سوق | issuer is free text today | no — evidence only |
| رقم السجل · الاسم · العنوان | not person-unique | never |

الجنسية is **not** the issuer. A Syrian may hold a document issued by Lebanon, so inferring one
from the other would merge strangers.

An identifier that already belongs to someone else is **never** transferred: the save is
refused and the operator is shown who holds it, so they can reuse that person instead.

### Nobody types الرقم المرجعي — and nobody sees an empty box for it

**The field is not on the form at all.** It is computed: derived from the identifiers for a
soldier, issued from a sequence for everyone else. An empty box invites someone to fill it in,
and hand-typing is what produced `MIL-4471`, `MIL 4471` and `4471` for one soldier — three
people where there was one.

What the operator fills in instead are the fields the key is *made of*, and for a military
subject those are now **required**:

| Field | Why it is required |
|---|---|
| **الجهاز** (`security_branch`) | A serial is unique only *within* its force. `MIL-ARMY-4471` and `MIL-ISF-4471` are two people |
| **الرقم العسكري** (`military_id`) | The serial itself |

`آخر` is refused as a الجهاز: it is a catch-all, not a namespace, so two "other" forces sharing
a serial would collapse into one identity and pool two people's voice prints.

**A soldier whose serial is simply not known stays recordable.** An interview happens whether
or not the person can be identified; they are saved with no reference, and the system says so
rather than inventing one. What the server *does* refuse is a serial with **no usable force**
(`military_id_needs_security_branch`, 422) — that looks like identity evidence and is not.

The asymmetry with user accounts is deliberate. A **user** must supply both fields, because you
control your own staff records and there is no "we could not find out". A **subject** may not
be identifiable at all, and refusing the record would make the system unusable exactly when it
matters most.

**Overriding** exists only where a reference is *derived* and the paperwork does not fit the
rule. It is reached through **تعيين الرقم المرجعي يدوياً**, a control shown only to someone who
holds the permission — a deliberate action, not a box sitting open on every form. It needs
`subjects.reference.override`, which ADMIN holds and an investigator does not,
and it is not offered for civilians at all — their reference comes from a sequence, so there is
nothing to correct. When a soldier is overridden, the number the identifiers imply is
**reserved against the person chosen**, so a later investigator entering the same soldier
plainly lands on the same person rather than creating a second one.

`CIV-*` and `TMP-*` can **never** be hand-assigned, whatever permission the caller holds.
Typing `CIV-00009999` would squat a number the sequence has not reached; the day it arrives
there, that civilian is either refused or silently attached to the squatter. Reusing a `CIV-*`
that already exists is a different thing — that is selecting a person, and it is allowed.

### What a TMP reference does and does not guarantee

`TMP-2026-000123` guarantees a **unique record**. It does **not** mean the system can tell that
two undocumented people met in different sessions are the same human.

A civilian no longer needs one: having no papers does not make someone unclassified, so an
undocumented civilian is issued `CIV-*` like any other. TMP is for a person who has not been
classified **at all** yet.

Someone in that state, encountered twice with nothing trustworthy to identify them, legitimately
becomes two TMP identities. The system will **never** merge them on a matching name, a similar
name, the same role, session metadata or closeness in time — those are not identity evidence,
and no fuzzy matching is used. They are consolidated only when there is real evidence: papers
appear, an existing person is selected, an authorised operator consolidates them, or the voice
workflow establishes the identity under its normal confirmation rules. Both TMP references then
survive as aliases, so neither can be recreated later.

A TMP reference is also allocated **once**. Editing and re-saving a session never issues a new
one for the same participant.

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

* **رقم السجل + القضاء** are captured separately from the ID-card number — for Lebanese
  nationals the civil-registry entry, not the card, is the authoritative identifier.
* **القضاء and البلدة are two different fields, and only one of them identifies anybody.**
  `caza_code` is a code chosen from a fixed list and is part of the identity key, because
  رقم السجل repeats between أقضية. `place_of_registration` is free text — a note, never read by
  `derive_reference`. They once shared the single label *محل القيد (قضاء/بلدة)*, which made two
  quite different things look interchangeable; they are now **القضاء** and
  **البلدة / تفاصيل محل القيد**, the second marked *وصفي فقط*.
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
