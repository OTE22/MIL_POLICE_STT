# Troubleshooting

**Who this is for:** everyone. Find your symptom in the left column. The Arabic entries are
what you see on screen; the technical ones further down are for whoever maintains the system.

| Symptom (Arabic UI) | Cause | Fix |
|---|---|---|
| الخدمة المحلية غير متوفرة | agent not running / wrong port / browser blocked the local-network request | `curl http://127.0.0.1:17117/health`; on Windows check service `MilitarySTTAgent` (`nssm status` / Task Scheduler); accept the browser's local-network permission prompt; make sure the central origin is in `AGENT_ALLOWED_ORIGINS` |
| النموذج غير جاهز (STT) | Cohere model not provisioned, integrity mismatch, or load error | `python scripts/healthcheck.py --load`; provision with `HF_TOKEN` (gated repo); check `AGENT_MODEL_DIR` |
| النموذج غير جاهز (diarization) | `.nemo` file missing or NeMo import error | provision `--only diarization`; check torch/NeMo installation in the venv |
| تعذر تشغيل نموذج … على هذا الجهاز | model load failed at job time (VRAM, corrupt files) | see `agent.err.log` / `docker compose logs agent`; run with `AGENT_STT_DEVICE=cpu` to confirm files are fine; free GPU memory |
| الملف الصوتي غير مدعوم | extension/MIME/magic bytes rejected | use WAV/MP3/M4A/WEBM; re-export with FFmpeg |
| تعذر معالجة التسجيل الصوتي | ffprobe/ffmpeg failure, empty or corrupted audio | `ffprobe file`; ensure FFmpeg is on the *system* PATH of the service account |
| تعذر إرسال النتائج إلى الخادم. سيتم إعادة المحاولة | central unreachable, TLS error | results are kept locally and retried (`GET /jobs/{id}` shows `sync_state`); fix `AGENT_CENTRAL_URL`, CA bundle; `POST /jobs/sync/run` forces a retry |
| انتهت صلاحية تصريح المعالجة | more than `CENTRAL_PROCESSING_TOKEN_ACCEPT_TTL_SECONDS` between token issue and upload, or clock skew | retry; synchronize clocks (agent allows ±60 s) |
| `public_key_missing` in agent logs | central public key not installed | copy `central_public_key.pem` (see installation docs) |
| `token_replay` | the same token was submitted twice | request a new processing token (the UI does this automatically on retry) |
| Session stuck in قيد المعالجة | agent crashed mid-job | the agent marks interrupted jobs FAILED on restart; cancel via **إلغاء المهمة** or the central cancel endpoint and process again |
| `sha256_mismatch` on audio upload | the original file changed between processing and upload | never edit files in the agent's job directory; process again |
| nginx 502 | backend not healthy yet / migration failing | `docker compose logs backend` |
| `CUDA requested but not available` | driver/toolkit mismatch | check `nvidia-smi`; the agent falls back to CPU and reports it |
| **تسجيل بصمة الصوت** disabled: *لا توجد بصمة صوت لهذا المتحدث* | the speaker has no voice embedding — **either** the agent cannot compute one **or** this recording predates the model | read **حالة نموذج بصمة الصوت** in the recording tab first; see *Voice prints* below — the two causes need opposite fixes |
| **حالة نموذج بصمة الصوت: غير معروف** | the agent does not report `speaker_id` at all — its build predates voice identification | redeploy the agent (`deploy/deploy-edge.sh`). **Reprocessing will not help** |
| **حالة نموذج بصمة الصوت: النموذج غير مثبّت** | `speakerverification_speakernet.nemo` is not under `AGENT_MODEL_DIR` | `python scripts/provision_models.py --model-dir ./models --only speaker_id`, then restart the agent |
| **تسجيل بصمة الصوت** disabled: *حدِّد هوية المتحدث أولاً* | the speaker has a label but no canonical person | press **اختيار الشخص** and pick the person. A free-text name is not an identity |
| `military_id_needs_security_branch` (422) saving a subject | a الرقم العسكري was entered with no الجهاز, or with `آخر` | pick a real force. A serial is unique only within its force, so the serial alone is not identity evidence |
| **الرقم المرجعي** is absent | the reference system has been retired | select the person by name; internal UUIDs preserve links. Reload older clients after deployment. |
| A soldier was saved with **no** الرقم المرجعي | their الرقم العسكري was not known, which is allowed | nothing is broken: they simply cannot be voice-enrolled until identified. Add the serial later and re-save |
| Two fields looked like **محل القيد** | they were two different things sharing one label | now **القضاء** (part of the identity key) and **البلدة / تفاصيل محل القيد** (descriptive only) |
| The same person appears twice in **اختيار الشخص**, under two names | an old build: sections were fed by three different shapes and de-duplication knew only one | update the frontend. Every row now comes from `GET /investigations/{id}/people` |
| A setting changed in **إعدادات النظام** reverted after a restart | by design: the page changes the RUNNING server; boot re-reads `.env` | make it permanent in `.env` — see [system-settings.md](system-settings.md) |
| An investigator is listed in **مُحقّقو الجلسة** but greyed out | their profile has no `الجهاز` or `الرقم العسكري`, so no الرقم المرجعي could be derived and they are not a registry person | complete the profile in **إدارة المستخدمين**, then re-save the session's investigators. The row names the missing fields |
| A user cannot be created: 422 on `security_branch` | either it was omitted, or `آخر`/`OTHER` was chosen | pick a real force. `OTHER` is a catch-all, not a namespace — two "other" forces sharing a serial would collapse into one identity |
| `identity_change_not_permitted` (403) | the caller holds `speakers.assign` but not `voice.identify` | labelling and identifying are separate authorities — have someone with `voice.identify` bind the person |
| A person gets no suggestions although they are well enrolled | their prints are split across two canonical identities, so two of their own prints look like rival people and the matcher abstains | consolidate the identities (see [voice-enrollment-guide.md](voice-enrollment-guide.md) §7d). **Do not** edit `voice_enrollments.person_reference` — matching groups by `identity_id` |
| **فحص البصمات الصوتية** says **تحتاج مراجعة** (2+ مجموعات صوتية) | the person's active prints fall into sets that match internally but not each other — usually a print enrolled from the **wrong speaker**, sometimes extremely different recording conditions | nothing is broken or auto-removed: each print in the dialog links to its source session. Listen, decide which group is really this person, and **تعطيل/حذف** the rest. The system never picks the "real" group itself |
| The **فحص البصمات الصوتية** button is greyed out | the person has no *active* prints, or the row is a legacy print without a canonical identity | reactivate a print (or enrol one); for a legacy row, bind the person to an identity first |
| Saving إعدادات النظام refused: `near_duplicate_must_exceed_match_threshold` | the save would leave عتبة البصمة شبه المكررة at or below عتبة اقتراح الهوية, which would make the check's labels contradictory | keep the near-duplicate bar above the suggestion threshold; the values are checked as they *would be* after the save, so adjust whichever you edited |
| Every س in the محضر is empty | No speaker on the session is marked **المحقق**, so the builder refuses to invent a questioner and keeps each turn as an answer-only block | Set the roles in **المتحدثون**, then press **تحديث من النص المنقح** in the composer |
| **تم تعديل التفريغ بعد بناء هذه المسودة** | Someone corrected the transcript after the draft was built. The draft is deliberately unchanged | Press **تحديث من النص المنقح** to rebuild from the current text — your report wording is replaced, knowingly |
| **إنشاء المحضر النهائي** is disabled | One of the finalization gates is unmet | The archive panel lists exactly which: a missing header field, an unidentified speaker, no included content, or no valid template |
| **لا يوجد قالب رسمي معتمد وفعال لإنشاء المحضر النهائي** | Production is running on the bundled development template (`نموذج غير معتمد`) | القالب الرسمي للمحضر → رفع قالب بديل → تفعيل. Drafting works meanwhile; only issuing is blocked |
| Uploading a template says `unknown_placeholders` / `missing_placeholders` | The Word file uses a name that is not in the catalogue, or lacks the `qa_blocks` loop | The catalogue is printed on the template page. The dialogue loop is required — one template must print 5 or 300 questions |
| Word reports "unknown tag 'endfor'" when validating | The `{%tr for %}` and `{%tr endfor %}` markers share a table row | Each marker needs its **own** row; docxtpl repeats the rows between them |
| **خدمة اقتراح الصياغة غير متوفرة على هذا الجهاز** | No formalization runtime resolved. A normal, supported state | `GET /api/llm/capabilities` gives the reason: no key (development), no local runtime, or no approved model provisioned (production). The محضر is still written by hand |
| A فصحى suggestion reads like a conversation ("لم يتم تزويدي بنص…") | The model answered instead of formalizing — usually because the source text was placeholder or meaningless | **رفض** it. Approving would put model chatter into an official document |
| **غير مطابق** when verifying an issued report | The archived .docx no longer hashes to what was recorded | Do not submit that copy. Investigate the storage; the report can be re-issued as a new version from a reopened draft |
| A report cannot be edited: `report_is_final` | It has been issued, and an issued محضر is immutable | **إعادة فتح للتصحيح** returns the draft to editable; the next issue becomes version N+1 and the earlier versions stay downloadable |

Logs: central `docker compose logs -f backend nginx`; agent `docker compose logs -f agent`
or `C:\ProgramData\InvestigationAI\agent\agent.err.log` (NSSM) / `journalctl -u military-stt-agent`.

---

## Following one request through the backend

Every response carries an `X-Request-ID` header, and every 500 body includes
`"request_id"`. That id is stamped on **every log record** the request produced:

```bash
grep '"request_id": "<the id>"' storage/logs/backend.jsonl | jq
```

gives the access line (route, status, duration, user), any service decisions (e.g. the
voice-matching verdict with its scores), slow-query warnings, and the full traceback if it
crashed. The file lives on the host and **survives `--force-recreate`** - unlike
`docker logs`. To watch a subsystem in detail without drowning, raise just its logger:
`CENTRAL_LOG_LEVELS=app.services.voice_matching=DEBUG` and restart the backend.

## Voice prints: capability vs embedding

On the speaker card these two look identical, and they need opposite fixes. Always establish
which one you have **before** reprocessing anything.

```
curl -s http://127.0.0.1:17117/model-status | python -m json.tool | grep -A 8 speaker_id
```

| What you see | Meaning | Fix |
|---|---|---|
| `"state": "READY"` | the model is loaded and working | the recording predates it — reprocess the recording |
| `"state": "PROVISIONED"` | found, not yet loaded | normal before the first job; it loads on demand |
| `"state": "NOT_PROVISIONED"` | the `.nemo` is not where the agent expects it | provision it, then restart the agent |
| `"state": "ERROR"` | it tried to load and failed | `docker compose logs agent` — the reason is logged |
| **no `speaker_id` key at all** | the agent build predates the feature | redeploy the agent |

**Reprocessing only helps in the first row.** In every other case the agent has nothing to
compute an embedding with, so it produces the same nothing again.

A quick way to tell what produced an existing result: the agent keeps every job's payload at
`/data/jobs/<job_id>/result.json`, and the job history survives container recreation in
`/data/agent.sqlite3`.

```bash
docker exec mstt-agent python -c "import json;d=json.load(open('/data/jobs/<job_id>/result.json'));print('voice_identification' in d, d.get('voice_identification'))"
```

`False` — the key is absent entirely — means a build from before voice identification existed.
`True` with `None` means a current agent that computed no embedding for that job (too little
speech, or the model was unavailable at the time).

The agent's own logs record every skip explicitly, one line per speaker:
`no embedding for SPEAKER_00 (speaker_id_audio_too_short)` or
`speaker identification unavailable: …`. Note that recreating the container discards those
logs — read them before `docker compose up --force-recreate`, or use the result payloads
above, which persist.
