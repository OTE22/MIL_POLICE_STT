# Using the system, step by step

**Who this is for:** anyone who runs interviews and produces reports. No technical
knowledge is assumed. Follow it in order the first time; afterwards use it as a reference.

**What you need before you start**

- The web address of your unit's server, from whoever installed it
  (something like `https://central.unit.local:8443` or `https://192.168.10.50:8443`).
- Your username and password.
- On the computer you will record with: the local AI program already installed. You can
  tell from the **التسجيل** tab — it shows **حالة الخدمة: جاهز** when it is ready.

---

## The whole journey on one page

```
  1. Sign in
  2. Create the session (إنشاء جلسة جديدة)        ← who is being interviewed
  3. Record or upload the audio (التسجيل)
  4. Wait for processing                            ← the AI works on YOUR computer
  5. Read and correct the text (النص المفرغ)
  6. Say who each speaker is (المتحدثون)
  7. (optional) Save a voice print
  8. Produce the محضر (إنشاء محضر تحقيق)
```

Steps 1–6 are the normal day. Steps 7 and 8 are done when you need them.

---

## 1. Signing in

Open the server address in your browser. Enter your username and password.

The first time, you are asked to change your password. That is normal and required.

> **The browser warns that the connection is not private.** On a unit LAN this usually
> means the server uses a self-signed certificate. Ask your administrator whether that is
> expected before continuing — if it is, they can install the certificate on your machine
> and the warning stops.

---

## 2. Create the session

**الجلسات → إنشاء جلسة جديدة**

A **جلسة** is one interview. Fill in:

| Field | Notes |
|---|---|
| **العنوان** | A short title you will recognise later. |
| **التاريخ**, **الوقت**, **الموقع** | When and where the interview happened. |
| **المحققون** | Who is conducting it. Pick from the list. |
| **الشخص** (the interviewed person) | See below — this is the part that matters most. |

Fields marked with a red **\*** are required. The form will not save without them.

### About the interviewed person

You do **not** type a reference number. The system works it out from the identity details
and shows it after saving:

- **A soldier** — choose **عسكري**, then the **الجهاز** (force) and the **الرقم العسكري**.
  Those two together produce the reference, e.g. `MIL-ARMY-20110078`. The force is
  required because serial numbers repeat between forces: Army 4471 and ISF 4471 are two
  different people.
- **A civilian** — choose **مدني** and fill in what is known. The system issues a
  `CIV-…` number automatically.
- **Identity not known** — that is allowed. Record what you have. The person simply cannot
  have a voice print until they are identified later.

> **Why it matters:** this number is how the system knows that the person in today's
> interview is the same person as in one from six months ago. Names repeat; numbers do not.

Enter the name as the name only — **علي عباس**, not **الرائد علي عباس**. The rank goes in
its own field. The report puts them together when it prints.

---

## 3. Record or upload the audio

Open the session, then the **التسجيل** tab.

First look at **حالة الخدمة**:

| It says | Meaning |
|---|---|
| **جاهز** | Ready. Continue. |
| **الخدمة المحلية غير متوفرة** | The AI program on this computer is not running. See [troubleshooting](troubleshooting.md). |
| **النموذج غير جاهز** | The program runs but a model is missing. Tell your administrator. |

Then either press record and conduct the interview, or upload an existing file
(WAV, MP3, M4A or WEBM).

**One session can hold several recordings.** A long interview split into three files is
normal — add them all to the same session, and the report can combine them in order.

> **Best results:** one microphone per person if you can, and ask people not to talk over
> each other. The system marks overlapping speech rather than hiding it, but overlapping
> voices are harder to transcribe accurately.
>
> The AI handles up to **four** speakers in one recording. More than that and the results
> get unreliable — the session warns you when you say to expect more.

---

## 4. While it processes

The audio is processed **on your own computer**, not on the server. Nothing but the
finished text is sent anywhere.

You will see the stages go by: preparing, separating the speakers, transcribing, finishing.
**Roughly one to three times the length of the recording** on a normal office computer —
a 30-minute interview may take under an hour. A computer with a graphics card is faster.

You can close the browser. The work continues, and the result is sent when it is done.
If the network drops, the finished text is kept on your computer and sent automatically
when the connection returns — nothing is lost.

---

## 5. Read and correct the text

Open the **النص المفرغ** tab. Each line shows who spoke, the time, and the words.

Click any line to hear that exact moment. Correct anything the AI misheard.

> **Your correction never erases the original.** The system keeps the AI's first version
> underneath, and the report can print either one. That is deliberate: it is what lets
> anyone check later what was actually said versus what was corrected.

---

## 6. Say who each speaker is

Open the **المتحدثون** tab. The AI separates voices but cannot know names, so they appear
as **SPEAKER_00**, **SPEAKER_01**…

For each one press **تحديد الهوية** and choose the person. Also set the **الصفة** (role) —
**المحقق** for the interviewer, **الشخص الذي تتم مقابلته** for the interviewed person.

**Setting the role matters more than it looks.** The report builds its
question-and-answer layout from it: turns by whoever is marked المحقق become the questions
(**س**), the replies become the answers (**ج**). With no investigator marked, every line
comes out as an answer with an empty question.

### If the system suggests a name

When someone already has a voice print, you may see:

```
اقتراح: علي عباس — درجة التطابق 81%      [تأكيد]  [تجاهل]
```

That is a **suggestion from the voice, and nothing more**. Listen, then press **تأكيد** if
it is right or **تجاهل** if it is not. Nothing is recorded as fact until you press one.

---

## 7. Voice prints (optional)

A **بصمة صوت** is a stored measurement of a person's voice that lets the system suggest
their name in future interviews.

To save one: identify the speaker first, then press **تسجيل بصمة الصوت**. Consent is
required and is recorded.

**Two to four prints per person is right** — recorded on different microphones or in
different rooms, so the person is recognised in varied conditions. Prints never compete
with each other; each one only widens the range of situations where they are recognised.

On the **بصمات الأصوات** page, **فحص البصمات الصوتية** checks whether one person's prints
really all sound like the same voice. If it reports **تحتاج مراجعة**, some print may have
been saved from the wrong speaker — listen to the source recordings and remove the odd one
out. Full details in [voice-enrollment-guide.md](voice-enrollment-guide.md).

---

## 8. Produce the محضر تحقيق

When the text is corrected and the speakers are named, press **إنشاء محضر تحقيق** on the
session page.

Briefly, in the composer you:

1. Fill in **رقم المحضر**, **موضوع القضية** and **مكان التحقيق** (all required).
2. Choose which recordings to include and whether to print the corrected or the original text.
3. Review the **س / ج** pairs — edit the wording, merge, split, or exclude a block
   (excluding a microphone test or a greeting is normal, and the reason is printed in the
   document rather than hidden).
4. Optionally request **الصياغة بالفصحى** — a formal-Arabic suggestion you approve, edit
   or reject. It never changes anything by itself, and it may be unavailable, which is fine.
5. Press **إنشاء المحضر النهائي**.

The result is a Word document in your organisation's official format, stored permanently
and verifiable. **An issued محضر cannot be edited** — a correction is issued as a new
version and the earlier ones remain.

The full guide is [investigation-report.md](investigation-report.md).

---

## When something looks wrong

| What you see | What to do |
|---|---|
| **الخدمة المحلية غير متوفرة** | The AI program on your computer is not running. Restart it, or ask your administrator. |
| Processing seems stuck | Check the **سجل النشاط** tab — it shows each stage. Long silences during transcription are normal. |
| A speaker has no name to choose | They must be recorded on the session first (**التفاصيل** tab), or added as a new person during **تحديد الهوية**. |
| **تسجيل بصمة الصوت** is greyed out | Either the speaker has no identity yet, or that recording has no voice measurement. The button's tooltip says which. |
| Every **س** in the report is empty | No speaker is marked **المحقق**. Set the roles, then press **تحديث من النص المنقح** in the composer. |
| The final report button is disabled | The report page lists exactly what is missing — a required field, an unidentified speaker, or no content. |
| A name is suggested that is clearly wrong | Press **تجاهل**. Then check that person's prints with **فحص البصمات الصوتية**. |

More symptoms, including technical ones, in [troubleshooting.md](troubleshooting.md).

---

## Things worth knowing

- **Nothing is deleted by the system.** Excluding a block from a report, deactivating a
  voice print or correcting text all leave the original in place.
- **Every action is recorded** in **سجل التدقيق** with who did it and when.
- **You only see the sessions you are entitled to see.** If a colleague can open something
  you cannot, that is the permission system working, not a fault.
- **The audio never leaves the computer that recorded it** unless the session is set up to
  upload it. The text does.
