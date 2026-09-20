# Which guide do I need?

Start here. Find the row that describes you, read those documents in that order, and
ignore the rest — most of this folder is written for engineers and you do not need it.

| I am… | Read, in this order | Skip |
|---|---|---|
| **An investigator using the system** | [daily-use.md](daily-use.md) → [investigation-report.md](investigation-report.md) | everything else |
| **Installing it on the server** | [production-deployment.md](production-deployment.md) → [../deploy/README.md](../deploy/README.md) | the model and architecture documents |
| **Installing it on a desktop** | [production-deployment.md](production-deployment.md) §6 → [windows-installation.md](windows-installation.md) *or* [linux-installation.md](linux-installation.md) | the server documents |
| **The administrator (accounts, settings)** | [daily-use.md](daily-use.md) → [system-settings.md](system-settings.md) → [security.md](security.md) | the pipeline internals |
| **A developer or maintainer** | [how-it-works.md](how-it-works.md) → [architecture.md](architecture.md) → [central-server.md](central-server.md) | nothing |
| **Something is broken** | [troubleshooting.md](troubleshooting.md) — a table of symptoms with fixes | — |
| **Reviewing voice prints or repeated speaker labels** | [voice-review-panel.md](voice-review-panel.md) → [voice-enrollment-guide.md](voice-enrollment-guide.md) | model internals unless troubleshooting |

---

## The system at a glance

Investigators record or upload an interview. The AI on **their own desktop** turns the
audio into Arabic text and works out who spoke when — **AI inference runs on that
machine**. The finished text goes to the central server; uploaded source recordings are
available for authorized playback. An investigator checks the transcript,
says who each speaker actually is, and turns the session into an official **محضر تحقيق**
Word document. The server keeps the record and the audit trail; it runs no AI itself.

```
   interview  ──►  the investigator's desktop  ──►  the server  ──►  محضر تحقيق
   (audio)          speech → Arabic text            review,          official
                    who spoke when                  identify         Word document
                    MODELS RUN HERE                 people
```

---

## Words you will see, in plain terms

The interface is in Arabic. These are the ones worth knowing before you start.

| On screen | What it means |
|---|---|
| **جلسة** (session) | One interview. Everything — recordings, text, people, the report — hangs off it. |
| **هوية الشخص** | Internal UUID linking a person across sessions and voiceprints; selected through the person picker, never typed. See [migration notes](person-identity-migration.md). |
| **التفريغ / النص المفرغ** | The transcript — the interview written out as text. |
| **المتحدثون** (speakers) | One card per identified person, with expandable recording observations. Unknown observations remain separate; `SPEAKER_*` codes appear in source details. |
| **تحديد الهوية** | Saying which real person a voice belongs to. Only a human does this. |
| **بصمة الصوت** (voice print) | A stored measurement of someone's voice, used to *suggest* their name in later interviews. A suggestion is never accepted automatically. |
| **تأكيد وحدة الهوية** | A recorded human decision that selected prints belong to the displayed person, within one group or across groups. It does not merge vectors or person records. |
| **محضر تحقيق** | The official Word document produced from a session. |
| **الصياغة بالفصحى** | An optional AI suggestion that rewrites colloquial Arabic into formal Arabic. You approve, edit or reject every one. |
| **القالب الرسمي** | The approved Word file that controls how the محضر *looks*. An administrator uploads it once. |

---

## Three rules the system will not bend

Worth knowing on day one, because they explain most of its behaviour:

1. **The AI never decides who someone is.** It can suggest a name from a voice; a person
   must confirm it. The same is true of the Arabic wording suggestions.
2. **Nothing overwrites the original.** A corrected transcript keeps the AI's original
   text beside it. An issued محضر is frozen — a correction becomes a new version.
3. **Editing a report never changes the evidence.** The recording, the transcript and the
   identities are untouched by anything you do in the report composer.

---

## Everything in this folder

**For everyone**
[daily-use.md](daily-use.md) · using the system, step by step
[investigation-report.md](investigation-report.md) · producing the محضر تحقيق
[voice-enrollment-guide.md](voice-enrollment-guide.md) · voice prints in practice
[troubleshooting.md](troubleshooting.md) · symptoms and fixes

**Installing**
[production-deployment.md](production-deployment.md) · the full deployment
[windows-installation.md](windows-installation.md) · a Windows desktop
[linux-installation.md](linux-installation.md) · a Linux desktop
[offline-provisioning.md](offline-provisioning.md) · models and air-gapped sites

**Administering**
[system-settings.md](system-settings.md) · the إعدادات النظام page
[security.md](security.md) · accounts, permissions, keys, what is protected

**Engineering**
[how-it-works.md](how-it-works.md) · one recording followed end to end
[architecture.md](architecture.md) · the two programs and why
[central-server.md](central-server.md) · schema, API, permissions
[database-relationships.md](database-relationships.md) · the ER model
[desktop-agent.md](desktop-agent.md) · the desktop program
[audio-pipeline.md](audio-pipeline.md) · validation, VAD, segmentation
[cohere-stt.md](cohere-stt.md) · the Arabic speech model
[nvidia-diarization.md](nvidia-diarization.md) · who-spoke-when
[speaker-identification.md](speaker-identification.md) · voice matching internals
[subject-identity.md](subject-identity.md) · how a person is identified
[testing.md](testing.md) · the test suites and results
