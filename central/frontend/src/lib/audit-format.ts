/* Turning audit records into something a person can read.
 *
 * Audit entries carry a `safe_metadata` object whose shape depends on the action. Printing
 * it as JSON is complete but unreadable, and it buries the one line that matters — who did
 * what — under identifiers nobody scans. So each action gets:
 *
 *   headline  the action, in Arabic (from AUDIT_ACTIONS)
 *   summary   the substance, as a short sentence: "SPEAKER_00 ← الرائد علي حسن · مطابقة ٨١٪"
 *   details   everything else, as labelled rows behind a toggle - nothing is discarded,
 *             because this is an evidence record, not a activity feed.
 */

import { AUDIT_ACTIONS, T, t } from "./i18n";
import { formatBytes, formatDuration } from "./format";

export type AuditCategory = "processing" | "transcript" | "voice" | "session" | "documents" | "users";

export const CATEGORY_LABELS: Record<AuditCategory, string> = {
  processing: "المعالجة",
  transcript: "النص المفرغ",
  voice: "بصمات الأصوات",
  session: "الجلسة",
  documents: "الوثائق",
  users: "المستخدمون",
};

const CATEGORY_OF: Record<string, AuditCategory> = {
  RECORDING_CREATED: "processing",
  RECORDING_UPLOADED: "processing",
  RECORDING_DELETED: "processing",
  LOCAL_PROCESSING_REQUESTED: "processing",
  LOCAL_PROCESSING_STARTED: "processing",
  DIARIZATION_STARTED: "processing",
  DIARIZATION_COMPLETED: "processing",
  DIARIZATION_FAILED: "processing",
  TRANSCRIPTION_STARTED: "processing",
  TRANSCRIPTION_COMPLETED: "processing",
  TRANSCRIPTION_FAILED: "processing",
  LOCAL_PROCESSING_COMPLETED: "processing",
  LOCAL_PROCESSING_FAILED: "processing",
  LOCAL_PROCESSING_CANCELLED: "processing",
  WORKSTATION_REGISTERED: "processing",

  TRANSCRIPT_RECEIVED: "transcript",
  TRANSCRIPT_SEGMENT_EDITED: "transcript",
  TRANSCRIPT_SEGMENT_RESTORED: "transcript",
  SPEAKER_RENAMED: "transcript",

  VOICE_ENROLLED: "voice",
  VOICE_ENROLLMENT_UPDATED: "voice",
  VOICE_ENROLLMENT_DELETED: "voice",
  VOICE_IDENTITY_SUGGESTED: "voice",
  VOICE_IDENTITY_CONFIRMED: "voice",
  VOICE_IDENTITY_REJECTED: "voice",
  VOICE_REMATCH_RUN: "voice",

  INVESTIGATION_CREATED: "session",
  INVESTIGATION_UPDATED: "session",
  INVESTIGATION_DELETED: "session",
  INVESTIGATOR_ASSIGNED: "session",
  INVESTIGATOR_UNASSIGNED: "session",

  SUBJECT_DOCUMENT_UPLOADED: "documents",
  SUBJECT_DOCUMENT_VIEWED: "documents",
  SUBJECT_DOCUMENT_DELETED: "documents",
};

export function auditCategory(action: string): AuditCategory {
  return CATEGORY_OF[action] ?? "users";
}

/** Outcome tone, used for the marker colour. */
export function auditTone(action: string): "ok" | "warn" | "danger" | "info" {
  if (action.endsWith("_FAILED") || action === "LOGIN_FAILED" || action.endsWith("_DELETED")) return "danger";
  if (action.endsWith("_CANCELLED") || action === "VOICE_IDENTITY_REJECTED" || action === "USER_DISABLED") return "warn";
  if (action.endsWith("_COMPLETED") || action === "VOICE_IDENTITY_CONFIRMED" || action === "VOICE_ENROLLED") return "ok";
  return "info";
}

/* ---- field labels and value formatting ---------------------------------- */

const FIELD_LABELS: Record<string, string> = {
  accept_by: "صالح للقبول حتى",
  accepted: "مقبول",
  agent_id: "معرّف الوكيل",
  agent_version: "إصدار الوكيل",
  consent_recorded: "الموافقة مسجّلة",
  device: "جهاز المعالجة",
  device_name: "اسم الجهاز",
  diarization_model: "نموذج فصل المتحدثين",
  diarization_model_revision: "مراجعة نموذج الفصل",
  display_name: "الاسم المعروض",
  document_type: "نوع الوثيقة",
  enrollment_id: "رقم البصمة",
  fields: "الحقول المعدّلة",
  investigators: "المحققون",
  subjects: "الأشخاص",
  speaker_role: "الصفة",
  location: "المكان",
  session_date: "التاريخ",
  notes: "الملاحظات",
  filename: "اسم الملف",
  is_active: "مفعّلة",
  job_id: "رقم المهمة",
  message: "الرسالة",
  mime_type: "نوع الملف",
  model: "النموذج",
  model_revision: "مراجعة النموذج",
  new: "بعد",
  new_edited_text: "النص بعد التعديل",
  original_text_preserved: "النص الأصلي محفوظ",
  person_name: "اسم الشخص",
  person_print_count: "عدد البصمات",
  person_reference: "الرقم المرجعي",
  previous: "الحالة السابقة",
  previous_edited_text: "النص قبل التعديل",
  progress: "التقدّم",
  reason: "السبب",
  recording_id: "رقم التسجيل",
  requires_confirmation: "يتطلب تأكيداً",
  roles: "الأدوار",
  runner_up: "المرشّح الثاني",
  scanned: "متحدثون تم فحصهم",
  scope: "النطاق",
  score: "درجة المطابقة",
  segments: "عدد المقاطع",
  self_service: "بمبادرة المستخدم",
  sequence: "رقم المقطع",
  session_number: "رقم الجلسة",
  sessions: "عدد الجلسات",
  sha256: "بصمة الملف (SHA-256)",
  size_bytes: "الحجم",
  source: "المصدر",
  speaker_label: "المتحدث",
  speakers: "عدد المتحدثين",
  state: "الحالة",
  status: "الحالة",
  stt_model: "نموذج تحويل الصوت إلى نص",
  stt_model_revision: "مراجعة نموذج التفريغ",
  suggested: "اقتراحات جديدة",
  suggested_name: "الاسم المقترح",
  title: "العنوان",
  transcript_id: "رقم النص",
  updated: "تم التحديث",
  username: "اسم المستخدم",
  voice_suggestions: "اقتراحات صوتية",
};

const SOURCE_LABELS: Record<string, string> = {
  BROWSER_RECORDING: "تسجيل من المتصفح",
  FILE_UPLOAD: "رفع ملف",
};

const SCOPE_LABELS: Record<string, string> = {
  session: "جلسة واحدة",
  all: "كل الجلسات غير المحددة",
};

/** Fields that are pure plumbing inside a session's own timeline. */
const REDUNDANT_IN_SESSION = new Set(["session_id"]);

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function isRatio(key: string): boolean {
  return key === "score" || key === "runner_up" || key === "progress";
}

export function formatFieldValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? T.yes : T.no;
  if (Array.isArray(value)) {
    if (!value.length) return "—";
    if (key === "fields") return value.map((v) => fieldLabel(String(v))).join("، ");
    return value.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join("، ");
  }

  if (key === "size_bytes" && typeof value === "number") return formatBytes(value);
  if (isRatio(key) && typeof value === "number") return `${Math.round(value * 100)}%`;
  if (key === "source" && typeof value === "string") return SOURCE_LABELS[value] ?? value;
  // Enum codes (COMPLETED, WITNESS, TRANSCRIBING …) have Arabic labels already.
  if (key === "status" && typeof value === "string") return t(`status_${value}`, value);
  if (key === "state" && typeof value === "string") return t(`state_${value}`, value);
  if (key === "previous" && typeof value === "string") return t(`state_${value}`, value);
  if (key === "speaker_role" && typeof value === "string") return t(`role_${value}`, value);
  if (key === "scope" && typeof value === "string") return SCOPE_LABELS[value] ?? value;
  if (key === "accept_by" && typeof value === "string") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString("ar", { hour12: false });
  }
  // Identifiers and hashes: enough to compare, not enough to drown the row.
  if (typeof value === "string" && (key === "sha256" || key.endsWith("_id"))) {
    return value.length > 16 ? `${value.slice(0, 12)}…` : value;
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/* ---- the one-line summary per action ------------------------------------ */

const s = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));
/** Wrap Latin text so it does not reorder inside an Arabic sentence. */
const ltr = (v: string): string => (v ? `⁦${v}⁩` : v);

/** Arabic counted nouns: 1 singular, 2 dual, 3-10 plural, 11+ accusative singular.
 *  "1 متحدثين" is simply wrong; the count has to agree with the noun. */
function counted(n: number, forms: { one: string; two: string; few: string; many: string }): string {
  if (n === 1) return forms.one;
  if (n === 2) return forms.two;
  if (n >= 3 && n <= 10) return `${n} ${forms.few}`;
  return `${n} ${forms.many}`;
}

const SPEAKERS = { one: "متحدث واحد", two: "متحدثان", few: "متحدثين", many: "متحدثاً" };
const SEGMENTS = { one: "مقطع واحد", two: "مقطعان", few: "مقاطع", many: "مقطعاً" };
const SUGGESTIONS = { one: "اقتراح واحد", two: "اقتراحان", few: "اقتراحات", many: "اقتراحاً" };
const pct = (v: unknown): string => (typeof v === "number" ? `${Math.round(v * 100)}%` : "");

/**
 * The substance of the entry as a short sentence, or null when the headline already
 * says everything (a bare LOGIN needs no elaboration).
 */
export function auditSummary(action: string, meta: Record<string, unknown> | null): string | null {
  const m = meta ?? {};
  const speaker = ltr(s(m.speaker_label));

  switch (action) {
    case "SPEAKER_RENAMED": {
      // previous/new are objects: { display_name, speaker_role }. A rename may change
      // the name, the role, or both - say which, rather than repeating one unchanged value.
      const before = (m.previous ?? {}) as Record<string, unknown>;
      const after = (m.new ?? {}) as Record<string, unknown>;
      const nameFrom = s(before.display_name);
      const nameTo = s(after.display_name);
      const roleFrom = s(before.speaker_role);
      const roleTo = s(after.speaker_role);
      const parts: string[] = [];
      if (nameFrom !== nameTo) parts.push(`«${nameFrom || T.unnamed}» ← «${nameTo || T.unnamed}»`);
      if (roleFrom !== roleTo) {
        parts.push(`${fieldLabel("speaker_role")}: ${t(`role_${roleFrom}`, roleFrom || T.unnamed)} ← ${t(`role_${roleTo}`, roleTo || T.unnamed)}`);
      }
      if (!parts.length) parts.push(nameTo || t(`role_${roleTo}`, roleTo) || T.unnamed);
      return `${speaker}: ${parts.join(" · ")}`;
    }
    case "VOICE_IDENTITY_SUGGESTED":
      return `${speaker} ← ${s(m.suggested_name)} · ${T.auditMatchScore} ${pct(m.score)}`;
    case "VOICE_IDENTITY_CONFIRMED":
      return `${speaker} ← ${s(m.display_name) || s(m.suggested_name)} · ${T.auditConfirmedByHuman}`;
    case "VOICE_IDENTITY_REJECTED":
      return `${speaker} · ${T.auditSuggestionDismissed} (${s(m.suggested_name)})`;
    case "VOICE_ENROLLED":
      return `${s(m.person_name)} · ${fieldLabel("person_reference")} ${s(m.person_reference)}`;
    case "VOICE_ENROLLMENT_DELETED":
      return `${s(m.person_name)} · ${fieldLabel("person_reference")} ${s(m.person_reference)}`;
    case "VOICE_REMATCH_RUN": {
      const scope = SCOPE_LABELS[s(m.scope)] ?? s(m.scope);
      const n = typeof m.suggested === "number" ? m.suggested : 0;
      return `${scope} · ${n === 0 ? T.auditNoNewSuggestions : counted(n, SUGGESTIONS)}`;
    }
    case "TRANSCRIPT_SEGMENT_EDITED":
      return `${T.auditSegment} ${s(m.sequence)} · ${speaker}`;
    case "TRANSCRIPT_RECEIVED":
      return ltr(s(m.stt_model).split("/").pop() ?? "") || null;
    case "RECORDING_CREATED":
      return [ltr(s(m.filename)), SOURCE_LABELS[s(m.source)] ?? s(m.source)].filter(Boolean).join(" · ");
    case "RECORDING_UPLOADED":
      return typeof m.size_bytes === "number" ? ltr(formatBytes(m.size_bytes)) : null;
    case "LOCAL_PROCESSING_COMPLETED": {
      const parts: string[] = [];
      // `speakers` is the list of labels, not a count.
      const nSpeakers = Array.isArray(m.speakers) ? m.speakers.length : m.speakers;
      if (typeof nSpeakers === "number") parts.push(counted(nSpeakers, SPEAKERS));
      if (typeof m.segments === "number") parts.push(counted(m.segments, SEGMENTS));
      if (typeof m.voice_suggestions === "number" && m.voice_suggestions > 0) {
        parts.push(counted(m.voice_suggestions, SUGGESTIONS));
      }
      return parts.join(" · ") || null;
    }
    case "INVESTIGATION_CREATED":
      return [s(m.session_number), s(m.title)].filter(Boolean).join(" · ");
    case "INVESTIGATION_UPDATED":
      return Array.isArray(m.fields) && m.fields.length
        ? `${fieldLabel("fields")}: ${(m.fields as string[]).map(fieldLabel).join("، ")}`
        : s(m.status) || null;
    case "SUBJECT_DOCUMENT_UPLOADED":
    case "SUBJECT_DOCUMENT_VIEWED":
    case "SUBJECT_DOCUMENT_DELETED":
      return s(m.document_type) || null;
    case "USER_CREATED":
      return [s(m.username), Array.isArray(m.roles) ? (m.roles as string[]).join("، ") : ""]
        .filter(Boolean)
        .join(" · ");
    case "USER_DISABLED":
    case "USER_ENABLED":
      return s(m.username) || null;
    case "LOGIN_FAILED":
      return [s(m.username), s(m.reason)].filter(Boolean).join(" · ");
    case "WORKSTATION_REGISTERED":
      return s(m.device_name) || null;
    default:
      return null;
  }
}

/** Fields already conveyed by the summary; showing them again is noise. */
const SUMMARISED: Record<string, string[]> = {
  SPEAKER_RENAMED: ["speaker_label", "previous", "new"],
  VOICE_IDENTITY_SUGGESTED: ["speaker_label", "suggested_name", "score"],
  VOICE_IDENTITY_CONFIRMED: ["speaker_label", "display_name", "suggested_name", "accepted"],
  VOICE_IDENTITY_REJECTED: ["speaker_label", "suggested_name", "accepted", "display_name"],
  VOICE_ENROLLED: ["person_name", "person_reference"],
  VOICE_ENROLLMENT_DELETED: ["person_name", "person_reference"],
  VOICE_REMATCH_RUN: ["scope", "suggested"],
  TRANSCRIPT_SEGMENT_EDITED: ["sequence", "speaker_label"],
  TRANSCRIPT_RECEIVED: ["stt_model"],
  RECORDING_CREATED: ["filename", "source"],
  RECORDING_UPLOADED: ["size_bytes"],
  LOCAL_PROCESSING_COMPLETED: ["speakers", "segments", "voice_suggestions"],
  INVESTIGATION_CREATED: ["session_number", "title"],
  INVESTIGATION_UPDATED: ["fields"],
  SUBJECT_DOCUMENT_UPLOADED: ["document_type"],
  SUBJECT_DOCUMENT_VIEWED: ["document_type"],
  SUBJECT_DOCUMENT_DELETED: ["document_type"],
  USER_CREATED: ["username", "roles"],
  USER_DISABLED: ["username"],
  USER_ENABLED: ["username"],
  LOGIN_FAILED: ["username", "reason"],
  WORKSTATION_REGISTERED: ["device_name"],
};

export interface AuditDetail {
  key: string;
  label: string;
  value: string;
}

/** Everything the summary did not already say, labelled. Nothing is dropped silently. */
export function auditDetails(
  action: string,
  meta: Record<string, unknown> | null,
  opts: { withinSession?: boolean } = {},
): AuditDetail[] {
  if (!meta) return [];
  const covered = new Set(SUMMARISED[action] ?? []);
  return Object.entries(meta)
    .filter(([k]) => !covered.has(k))
    .filter(([k]) => !(opts.withinSession && REDUNDANT_IN_SESSION.has(k)))
    .map(([k, v]) => ({ key: k, label: fieldLabel(k), value: formatFieldValue(k, v) }));
}

export function auditHeadline(action: string): string {
  return AUDIT_ACTIONS[action] ?? action;
}

/* ---- collapsing a processing run ---------------------------------------- */

/** The stages one recording passes through. Individually they are noise; together
 *  they are one event: "this recording was processed". */
const PIPELINE = new Set([
  "LOCAL_PROCESSING_REQUESTED",
  "LOCAL_PROCESSING_STARTED",
  "DIARIZATION_STARTED",
  "DIARIZATION_COMPLETED",
  "DIARIZATION_FAILED",
  "TRANSCRIPTION_STARTED",
  "TRANSCRIPTION_COMPLETED",
  "TRANSCRIPTION_FAILED",
  "TRANSCRIPT_RECEIVED",
  "LOCAL_PROCESSING_COMPLETED",
  "LOCAL_PROCESSING_FAILED",
  "LOCAL_PROCESSING_CANCELLED",
]);

export function isPipelineAction(action: string): boolean {
  return PIPELINE.has(action);
}

export interface TimelineEntry {
  id: string;
  action: string;
  username: string | null;
  created_at: string;
  safe_metadata: Record<string, unknown> | null;
}

export interface ProcessingRun {
  kind: "run";
  id: string;
  startedAt: string;
  endedAt: string;
  username: string | null;
  outcome: "ok" | "failed" | "cancelled" | "running";
  durationSeconds: number | null;
  /** Newest-first, as received. */
  stages: TimelineEntry[];
  summary: string | null;
}

export type TimelineRow = ProcessingRun | { kind: "entry"; id: string; entry: TimelineEntry };

/** Two pipeline events further apart than this belong to different runs. */
const RUN_GAP_MS = 15 * 60 * 1000;

/**
 * Collapse consecutive pipeline events into one row per run.
 *
 * Entries arrive newest-first. Grouping is by adjacency and time proximity rather than a
 * job id, because most stage events only carry the session id — and a session processes
 * one recording at a time, minutes apart, so adjacency is reliable here.
 */
export function groupTimeline(entries: TimelineEntry[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  let buf: TimelineEntry[] = [];

  const flush = () => {
    if (!buf.length) return;
    if (buf.length === 1) {
      rows.push({ kind: "entry", id: buf[0].id, entry: buf[0] });
      buf = [];
      return;
    }
    const newest = buf[0];
    const oldest = buf[buf.length - 1];
    const done = buf.find((e) => e.action === "LOCAL_PROCESSING_COMPLETED");
    const failed = buf.find((e) => e.action.endsWith("_FAILED"));
    const cancelled = buf.find((e) => e.action === "LOCAL_PROCESSING_CANCELLED");
    const ms = new Date(newest.created_at).getTime() - new Date(oldest.created_at).getTime();
    rows.push({
      kind: "run",
      id: `run-${oldest.id}`,
      startedAt: oldest.created_at,
      endedAt: newest.created_at,
      username: oldest.username ?? newest.username,
      outcome: failed ? "failed" : cancelled ? "cancelled" : done ? "ok" : "running",
      durationSeconds: Number.isFinite(ms) && ms > 0 ? ms / 1000 : null,
      stages: buf,
      summary: done ? auditSummary("LOCAL_PROCESSING_COMPLETED", done.safe_metadata) : null,
    });
    buf = [];
  };

  for (const e of entries) {
    if (!isPipelineAction(e.action)) {
      flush();
      rows.push({ kind: "entry", id: e.id, entry: e });
      continue;
    }
    if (buf.length) {
      const gap = new Date(buf[buf.length - 1].created_at).getTime() - new Date(e.created_at).getTime();
      if (Math.abs(gap) > RUN_GAP_MS) flush();
    }
    buf.push(e);
  }
  flush();
  return rows;
}

export function runOutcomeLabel(outcome: ProcessingRun["outcome"]): string {
  switch (outcome) {
    case "ok": return T.auditRunCompleted;
    case "failed": return T.auditRunFailed;
    case "cancelled": return T.auditRunCancelled;
    default: return T.auditRunRunning;
  }
}

export function runDuration(run: ProcessingRun): string | null {
  return run.durationSeconds && run.durationSeconds >= 1 ? formatDuration(run.durationSeconds) : null;
}
