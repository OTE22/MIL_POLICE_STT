# إعدادات النظام — runtime settings from the interface

**Who this is for:** administrators. Everything here changes a running server immediately,
so read the cautions before changing a threshold.

The **إعدادات النظام** page changes a running server without touching files or restarting
anything. It exists for the moments an administrator needs a knob *now*: raising log detail
while chasing a problem, widening a token window for a slow workstation, or adjusting the
voice-matching threshold after measuring real recordings.

## Who sees it, and where

Administrators only (`system.configure` — held by ADMIN). It appears at the bottom of the
sidebar under الإدارة, with a gear icon. Investigators do not see the entry, and the API
behind it returns 403 to them.

## How to use it

1. Open **إعدادات النظام** from the sidebar.
2. Change any values. The **حفظ** button stays disabled until something differs, then shows
   how many settings you changed — e.g. **حفظ (2)**.
3. Press **حفظ**. Only the changed values are sent; a toast confirms
   *حُفظت الإعدادات وطُبِّقت فوراً*.

If any single value is invalid (out of bounds, wrong type), the **whole save is rejected**
and nothing is applied — the page never half-applies a change. Every field states its
allowed range under it.

One rule crosses fields: **عتبة البصمة شبه المكررة must stay above عتبة اقتراح الهوية**.
Otherwise فحص البصمات الصوتية could call the same pair of prints both "near-duplicate" and
"incoherent" at once. A save that would end in that state is refused whole
(`near_duplicate_must_exceed_match_threshold`) — checked against the values as they *would
be* after the save, whichever of the two you edited.

## When each change takes effect

Every setting on the page applies to the running server **immediately** — that is the
admission rule for being on the page at all. "Immediately" means slightly different things
per setting, and the difference matters:

| Setting (Arabic label) | Takes effect |
|---|---|
| مستوى السجلّ العام | The next log record. Set DEBUG and even health-check lines start appearing within a second |
| مستويات لسجلّات محددة | The next record of that logger. Removing an override returns the logger to inheriting the root level — it does not stay stuck |
| عتبة الاستعلام البطيء | The next database query |
| عتبة اقتراح الهوية / هامش الغموض | The next matching run — the next recording an agent submits, or the next **إعادة فحص البصمات**. Already-made suggestions are not re-decided. عتبة اقتراح الهوية is also the coherence bar of the next **فحص البصمات الصوتية** |
| عتبة البصمة شبه المكررة | The next **فحص البصمات الصوتية** run. Advisory only — it labels near-duplicate prints in the check result; nothing is refused or removed |
| مدة صلاحية جلسة الدخول | **New logins only.** Sessions already signed in keep the lifetime they were issued with |
| مهلة قبول تصريح المعالجة (ثوانٍ) / مهلة إرسال النتائج (**دقائق**) | **Newly issued tokens only.** A token already handed to a workstation keeps its original windows |
| الحد الأقصى لحجم الملف الصوتي (**ميغابايت**) | The next upload validation |
| محضر التحقيق: تفعيل اقتراح الصياغة، الحرارة، المهلة، أقصى طول نص | The next فصحى suggestion. Disabling hides the controls entirely; the محضر is still written by hand |
| محضر التحقيق: مصدر خدمة الصياغة (`auto`/`local`/`off`) | The next suggestion. **Production is local-only whatever this says** — a cloud provider is refused in code |
| محضر التحقيق: النماذج المعتمدة وحدود ذاكرة البطاقة | The next resolution of the local profile. The model must already be provisioned; nothing is ever downloaded |

## Changes do not survive a restart — deliberately

The page changes the **running process**. When the server restarts, it reads `.env` again
and every value returns to what the file says. The blue banner on the page states this.

This is a safety property, not a limitation: an interactive mistake — a threshold set too
low, DEBUG left on for a week — is always one restart away from undone, and the file on
disk remains the single reviewed source of truth for how the system boots.

**To make a change permanent**, put it in the server's `.env` (the compose file passes
these through) and restart:

```bash
CENTRAL_LOG_LEVEL=INFO
CENTRAL_LOG_LEVELS=app.services.voice_matching=DEBUG
CENTRAL_SLOW_QUERY_MS=200
```

Threshold/margin, token lifetimes and the upload cap follow the same pattern with their
`CENTRAL_*` names (see [central-server.md](central-server.md)).

**Units:** the page speaks human units — upload cap in **megabytes**, result-sync window in
**minutes** — but the stored values and the `.env` variables remain canonical: bytes
(`CENTRAL_MAX_UPLOAD_BYTES=2147483648` = 2048 MB on the page) and seconds
(`CENTRAL_PROCESSING_TOKEN_SUBMIT_TTL_SECONDS=86400` = 1440 minutes). When making a page
change permanent in `.env`, convert back.

## Every change is on the record

Each saved change writes one log line — old value, new value, **who changed it**, and the
request id:

```
INFO [cfg-demo-1] app.admin: config changed log_level: INFO -> DEBUG
```

Visible in `docker compose logs backend` and permanently in
`storage/logs/backend.jsonl` (which survives container recreation):

```bash
grep "config changed" storage/logs/backend.jsonl | jq
```

## What is deliberately NOT on the page

Secrets (JWT secret, database URL, signing-key paths, bootstrap credentials) and
boot-structural values (storage root, CORS). The page renders only the backend's whitelist,
so these cannot appear in a browser even by mistake, and nothing that requires a restart is
offered as if it worked live.

## Cautions

* **عتبة اقتراح الهوية is calibrated.** 0.65 sits between the measured same-speaker band
  (0.76–0.90) and different-speaker band (0.34–0.52) on the reference recordings. Lowering
  it manufactures wrong suggestions; if a known voice is not being suggested, the better fix
  is usually **another enrolled print** of that person under the current recording
  conditions, not a lower bar for everyone.
* **The approved model names are a decision, not a guess.** The resolver picks the
  strongest profile this hardware supports *and* whose model is already installed. Free VRAM
  is not permission to load an untested model into an official workflow — benchmark first,
  then set the name here.
* **DEBUG is loud.** It includes every health poll and, with `app.sql=DEBUG`, every query.
  Use it for the minutes you need it, then put INFO back — or rely on the restart to do it.
* **The thresholds are a probe as well as a policy.** Because فحص البصمات الصوتية reads
  عتبة اقتراح الهوية live, raising it temporarily and re-running a person's check shows how
  robustly their prints hold together (e.g. 3 components at 0.65 became 5 at 0.70 on the
  reference data). Put the calibrated value back when done — or let the restart do it.

## If something looks wrong

| Symptom | Meaning |
|---|---|
| The page is missing from the sidebar | The account lacks `system.configure` — administrators only |
| A save returns to the old values after a restart | By design. Put the value in `.env` to keep it |
| حفظ rejected with a validation message | One of the edited values is outside its stated range; nothing was applied |
