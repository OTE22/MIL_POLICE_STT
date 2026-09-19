# محضر تحقيق — turning a session into an official document

**Who this is for:** investigators who produce reports, and the administrator who owns the
Word template. No technical knowledge needed for sections 1-5 and 7.

**New to the system?** Start with [daily-use.md](daily-use.md).

The report is the last step of the workflow: recordings become a transcript, the transcript
becomes a reviewed dialogue, and the dialogue becomes a Word document that leaves the
building. This page explains how it works, what it deliberately refuses to do, and what an
operator must decide.

```
جلسة  ──►  recordings  ──►  STT + diarization  ──►  transcript reviewed
                                                         │
                                                         ▼
                                            chronological speaker turns
                                                         │
                                                         ▼
                                                  س/ج draft blocks
                                                         │
                                    ┌────────────────────┴────────────────────┐
                                    │        HTML composer (content)          │
                                    │  edit · merge · split · exclude · فصحى  │
                                    └────────────────────┬────────────────────┘
                                                         │  human approval
                                                         ▼
                                     ONE official Word template (layout)
                                                         │
                                                         ▼
                                       final DOCX · SHA-256 · archive · audit
```

---

## 1. The separation that everything else follows

**The organisation owns the layout. The investigator owns the content.**

Letterhead, page borders, fonts, margins, the هامش column, headers, footers, page numbering,
س:/ج: styling and the signature areas all live inside a real Word file that an administrator
edits in Word. The web application never touches any of it — there is no font selector, no
margin control, no signature-position editor, and there never will be.

The composer edits only *what the report says*: which recordings, which text, the header
fields, and the wording of every question and answer.

**The report is a DERIVED document.** Editing it never changes the recording, the transcript,
the speaker rows, the identities or the voice prints. That is enforced mechanically —
`tests/test_report_draft.py` hashes every transcript, segment and speaker row of the session
before and after each report operation and asserts the hash is unchanged.

---

## 2. Building the draft

Press **إنشاء محضر تحقيق** on a session that has at least one completed transcript.

**Recordings** — every recording with a transcript is selected by default; untick any you do
not want. Changing the selection rebuilds the dialogue, because it changes what is quoted.

**Text source** — **النص المنقّح** (the human-corrected text where a correction exists, the AI
text elsewhere) or **النص الأصلي** (the untouched machine output). Corrected is the default.
Switching re-quotes the evidence and rebuilds.

**Turns before questions.** Diarizers fragment one utterance into several segments. The
builder first stitches consecutive segments of the same speaker into a single *turn* — so
"هل تعرف" + "الشخص أحمد" + "ومنذ متى تعرفه؟" becomes one readable question — while keeping a
reference to every source segment.

**Pairing.** Turns by a speaker whose role is **المحقق** open a block; the answers that follow
close it. This is deliberately not naive alternation: an unanswered question stays its own
block, a second person answering the same question gets their own block with the question
repeated, and speech with no question in front of it becomes an answer-only block. **No
testimony is ever dropped.**

> If no speaker on the session is marked as the investigator, every turn becomes an
> answer-only block. That is correct — the system will not invent a questioner — but it is
> rarely what you want. Set the roles in the **المتحدثون** tab, then press
> **تحديث من النص المنقح**.

---

## 3. Editing, and what each control costs

| Control | What it does | What it does NOT do |
|---|---|---|
| Edit the س or ج text | Changes what will be printed | The transcript, and the block's stored source text, are untouched — the composer shows both |
| **دمج مع التالي** | Joins two adjacent blocks that diarization split | Loses no provenance: every source segment stays referenced |
| **تقسيم الجواب** | Splits one answer in two; the second half repeats the question | Neither half becomes anonymous |
| **استبعاد من المحضر** | Leaves a block out of the printed document | Deletes nothing. The block, its source text and the recording all remain, and the exclusion **is printed in an annex** |
| **إعادة الإدراج** | Puts an excluded block back | — |

Exclusion is for microphone tests, greetings and setup chatter. Because a selective omission
from an official document is a serious thing, the reasons are printed on the document itself
rather than left invisible.

---

## 4. Speakers must be people

A diarization label is not a person. The report prints:

* the **canonical registry name** when the speaker has an identity;
* a session-local display name marked **(غير موثّق في السجل)** when there is only a label;
* **متحدث غير محدد الهوية (SPEAKER_NN)** when there is neither — never a bare `SPEAKER_00`
  dressed up as a person.

Rank and name stay separate in the registry (`علي عباس` + `رائد`, never
`الرائد علي عباس` as one field); only the printed page joins them.

If any speaker who actually says something in the report is unidentified, finalization is
**refused** until either the identity is set or the investigator ticks the acknowledgement —
which is recorded with their name and the time.

---

## 5. الصياغة بالفصحى — optional AI, human decides

Colloquial Lebanese Arabic can be offered as Modern Standard Arabic for the report. The whole
feature is optional: with no model available, the composer says so and the investigator
writes the wording by hand.

The order is the invariant:

```
source text  ──►  suggestion (stored BESIDE the report text)  ──►  اعتماد / تعديل / رفض
                                                                          │
                                                                          ▼
                                                                   printed text
```

There is **no code path** from model output to printed text without a person. Asking twice
without deciding adopts nothing; rejecting keeps the offer on the record but changes nothing
that will be printed. Each block is formalized on its own — small inputs keep latency and
memory low and make the human comparison honest.

The model is instructed to preserve names, ranks, organisations, places, dates, times,
numbers, negation, uncertainty, attribution and chronology, and forbidden to summarise,
infer, resolve contradictions, strengthen an accusation or weaken a statement. Measured
example:

```
ما بعرف مين أخد السيارة، بس شفت أحمد حدها.
   →  لا أعلم من أخذ السيارة، إلا أنني رأيت أحمد بجانبها.        ✔ negation kept, nothing invented
   ✘  شاهدت أحمد وهو يأخذ السيارة.                                 would change the facts
```

Provenance stored per block: provider, runtime, model, temperature, a hash of the source text
and who approved it, when. Never the prompt, never a reasoning trace, never the API key.

### Where the model runs

| | development | production |
|---|---|---|
| Allowed runtimes | hosted NVIDIA catalogue **or** a local runtime | **local only** |
| Cloud fallback | — | **impossible**: refused in code when `CENTRAL_ENVIRONMENT=production`, not by configuration |
| Data rule | **synthetic or anonymised text only** | real content never leaves the machine |
| If unavailable | composer shows a note; workflow continues | identical |

Production detects the hardware once at startup (RAM, GPUs, VRAM, CUDA, runtime, installed
models) and picks the strongest **approved and already-provisioned** profile —
CPU_BASELINE / GPU_SMALL / GPU_MEDIUM / GPU_LARGE. It never downloads a model, and free VRAM
is not permission to load an unapproved one. `GET /api/llm/capabilities` reports what
resolved and why it fell back.

---

## 6. The official template

One approved format, with a version history. **القالب الرسمي للمحضر** (administrators only)
lets you download the current file, edit it in Word, upload the replacement, and activate it.

Validation gates **activation**, not upload: a bad file is stored so you can read why it
failed, but it can never become the form official documents print on. Refused: anything that
is not a real .docx, macros, external relationships, zip bombs, broken Jinja, unknown
placeholders, a missing `qa_blocks` loop, and attempts to reach Python internals.

Write placeholders where you want the value. The dialogue repeats from **one** block, so the
same template prints 5 or 300 questions and Word paginates by itself:

```
{%tr for qa in qa_blocks %}
  س: {{ qa.question }}
  ج: {{ qa.answer }}
{%tr endfor %}
```

Each `{%tr%}` marker needs its **own table row** — both in one cell is the usual cause of
"unknown tag 'endfor'". The full placeholder catalogue is published on the page itself.

**A fresh install ships a development template** marked **نموذج غير معتمد** so the composer
works on day one. In production the server **refuses to issue a final محضر on it** — upload
the approved file first. Drafting works meanwhile.

Template authoring notes: set complex-script fonts and paragraph direction in Word rather
than relying on invisible Unicode marks; embed fonts in the file if reviewers may not have
them; and note that Word field codes (page numbers, dates) refresh when the document is
*opened*, so a printed page can differ from the archived bytes — validation warns which parts
contain them.

---

## 7. Issuing, archiving, verifying

**إنشاء المحضر النهائي** validates, freezes, renders, hashes and archives — in that order.

Refused when: a required header field is empty (رقم المحضر، موضوع القضية، مكان التحقيق), no
block is included, a speaking participant is unidentified and unacknowledged, no valid
template is active, or (in production) the active template is the development stand-in.

What is frozen into the issued document: the header fields, the Q&A as printed, which blocks
were included and excluded, the selected recordings, the **exact transcript revisions**
(transcript id plus a SHA-256 of its segments' text), the text-source mode, the approved
wording, the template version, and the speaker attribution.

Stored per issue: the .docx, a `report-context.json` sidecar holding the exact rendering
input, and three hashes — of the document, of the context, and of the template version.

**Corrections never overwrite.** A finalized report is immutable; **إعادة فتح للتصحيح**
returns the draft to editable and the next issue becomes version N+1, while every earlier
version stays downloadable and verifiable.

**تحقق** recomputes the three hashes and answers **سليم** or **غير مطابق**. This is integrity
verification, not a digital signature: it proves the archived bytes are unchanged, and it
cannot vouch for a copy someone edited after downloading it. For submission, re-download from
the archive and verify before filing.

Filesystem and database cannot disagree in the dangerous direction: the file is written
first, the row second, and a failed insert deletes the file. Either a complete report with a
record, or nothing.

---

## 8. Permissions and audit

| Permission | Grants | Roles |
|---|---|---|
| `reports.read` | View drafts and the archive, download, verify | ADMIN, INVESTIGATOR, USER |
| `reports.generate` | Create and edit the draft, request Fusha, reopen for correction | ADMIN, INVESTIGATOR |
| `reports.finalize` | Issue the final official document | ADMIN, INVESTIGATOR |
| `reports.templates.manage` | Upload, validate and activate the official template | ADMIN |

Drafting and **issuing** are separate authorities on purpose. Every route is session-scoped:
a session you cannot open does not leak through its report.

Audited: `REPORT_DRAFT_CREATED / UPDATED / REFRESHED / REOPENED`, `REPORT_QA_EDITED /
EXCLUDED / RESTORED`, `REPORT_FUSHA_REQUESTED / APPROVED / REJECTED`, `REPORT_GENERATED`,
`REPORT_DOWNLOADED`, `REPORT_VERIFIED`, `REPORT_TEMPLATE_UPLOADED / ACTIVATED / DEACTIVATED`.

---

## 9. Settings

Under **محضر التحقيق** in إعدادات النظام: the Q&A cap, whether Fusha is enabled at all, its
temperature, timeout and maximum input length, the runtime mode (`auto` / `local` / `off`),
and the four approved model names with their VRAM thresholds. All take effect on the next
request.

Not configurable, by design: evidence immutability, the human-approval requirement for AI
wording, and the production local-only rule. Those are invariants in code.

---

## 10. When something looks wrong

| Symptom | Meaning |
|---|---|
| Every block has an empty question | No speaker is marked المحقق. Set roles, then تحديث من النص المنقح |
| **تم تعديل التفريغ بعد بناء هذه المسودة** | Someone corrected the transcript afterwards. The draft is deliberately unchanged; press تحديث من النص المنقح to rebuild (your wording is replaced) |
| Finalize button disabled | The archive panel lists exactly what is blocking it |
| **لا يوجد قالب رسمي معتمد وفعال** | Production with the development template active — upload and activate the approved one |
| **خدمة اقتراح الصياغة غير متوفرة** | No model resolved. Normal state; write the wording by hand. `GET /api/llm/capabilities` says why |
| A suggestion reads like a conversation | The model answered instead of formalizing. Reject it — approving it would put model chatter into an official document |
| **غير مطابق** on verify | The archived file no longer matches its recorded hash. Do not submit it; investigate the storage |

See also: [voice-enrollment-guide.md](voice-enrollment-guide.md) for identifying speakers
before reporting, and [system-settings.md](system-settings.md) for the tunables.
