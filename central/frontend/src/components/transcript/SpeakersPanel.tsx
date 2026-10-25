import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, http } from "@/api/client";
import type { Speaker, SpeakerRole, VoiceRematchOutcome } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDuration, speakerColor } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Badge, Field, useToast } from "@/components/ui";
import { IconCheck, IconChevronLeft, IconClock, IconFile, IconInfo, IconRefresh, IconSearch, IconShield, IconUsers, IconWave } from "@/components/Icons";
import { groupSpeakerObservations } from "@/lib/transcript-speakers";
import { VoiceEnrollButton, VoiceSuggestion } from "./VoiceSuggestion";
import { IdentifySpeakerDialog } from "@/components/voice/IdentifySpeakerDialog";
import { VoiceRematchResult } from "@/components/voice/VoiceRematchResult";
import { SpeakerPicker } from "./SpeakerPicker";
import "@/styles/speaker-workspace.css";

const ROLES: SpeakerRole[] = ["INVESTIGATOR", "SUBJECT", "WITNESS", "OTHER", "UNKNOWN"];
type SpeakerDraft = { role: SpeakerRole; notes: string };
type ReviewFilter = "all" | "suggested" | "pending" | "identified";

function SpeakerForm({ sessionId, speaker, onSaved, onReloadRequested, observationNumber, draft, onDraftChange }: {
  sessionId: string;
  speaker: Speaker;
  onSaved: (s: Speaker) => void;
  onReloadRequested: () => void;
  observationNumber: number;
  draft?: SpeakerDraft;
  onDraftChange: (draft: SpeakerDraft | null) => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [identifying, setIdentifying] = useState(false);
  const [busy, setBusy] = useState(false);
  const role = draft?.role ?? speaker.speaker_role;
  const notes = draft?.notes ?? speaker.notes ?? "";
  const editable = can("speakers.assign");
  const dirty = role !== speaker.speaker_role || notes !== (speaker.notes ?? "");

  const save = async () => {
    setBusy(true);
    try {
      const updated = await http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speaker.id}`, {
        speaker_role: role,
        notes: notes.trim() || null,
      });
      onSaved(updated);
      onDraftChange(null);
      toast.success(T.speakerSaved);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="speaker-review-form" data-testid="speaker-card" data-label={speaker.speaker_label}>
      {identifying && <IdentifySpeakerDialog initialMode="new" sessionId={sessionId} speaker={speaker}
        onClose={() => setIdentifying(false)} onIdentified={onReloadRequested} />}

      <div className="speaker-sample-strip">
        <span className="speaker-sample-icon"><IconWave /></span>
        <div className="speaker-sample-source">
          <strong>العينة الصوتية {observationNumber}</strong>
          <span>{speaker.recording_name ? <bdi>{speaker.recording_name}</bdi> : "من تسجيل الجلسة"}</span>
        </div>
        <span className="speaker-sample-metric"><IconClock />{formatDuration(speaker.total_seconds)}</span>
        <span className="speaker-sample-metric">{speaker.segment_count} مقاطع</span>
        <Link className="speaker-text-link" to={`/investigations/${sessionId}?tab=transcript`}>فتح النص <IconChevronLeft /></Link>
      </div>

      <section className="speaker-form-section" aria-labelledby={`identity-${speaker.id}`}>
        <div className="speaker-section-heading">
          <span className={`speaker-step-number ${speaker.identity_id ? "is-complete" : ""}`}>{speaker.identity_id ? <IconCheck /> : "١"}</span>
          <div><h4 id={`identity-${speaker.id}`}>تحديد هوية المتحدث</h4><p>اختر الشخص الذي ينتمي إليه هذا الصوت. يُحفظ الربط مباشرة.</p></div>
        </div>
        <VoiceSuggestion sessionId={sessionId} speaker={speaker} onDecided={(patch) => {
          onSaved({ ...speaker, ...patch });
          onReloadRequested();
        }} />
        {!speaker.identity_id && speaker.identification_status === "NONE" && <p className="speaker-field-hint" role="status">
          {speaker.has_voice_embedding ? "لا يوجد اقتراح محفوظ لهذه العينة. استخدم البحث عن اقتراحات لمقارنتها بالبصمات المحفوظة، أو اختر الشخص يدوياً." : "لا تتوفر بصمة صوتية لهذه العينة لإنتاج اقتراح. يمكنك اختيار الشخص يدوياً أو مراجعة معالجة التسجيل."}
        </p>}
        <SpeakerPicker sessionId={sessionId} speaker={speaker} onLinked={onReloadRequested}
          onAddNew={() => setIdentifying(true)} disabled={!editable || busy} />
        {speaker.display_name && !speaker.identity_id && <p className="speaker-field-hint" data-testid="speaker-not-identified">{T.speakerNeedsIdentity}</p>}
        {!editable && <p className="speaker-field-hint">عرض فقط — تعديل هوية المتحدث متاح للمستخدمين المخوّلين.</p>}
      </section>

      <section className="speaker-form-section" aria-labelledby={`details-${speaker.id}`}>
        <div className="speaker-section-heading">
          <span className="speaker-step-number">٢</span>
          <div><h4 id={`details-${speaker.id}`}>الصفة والملاحظات</h4><p>حدّد صفة المتحدث في هذه الجلسة، ثم احفظ التعديلات.</p></div>
        </div>
        <div className="speaker-fields">
          <Field label={T.speakerRole}>
            <select className="select" aria-label={T.speakerRole} value={role}
              onChange={(e) => onDraftChange({ role: e.target.value as SpeakerRole, notes })} disabled={!editable || busy}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`role_${r}`)}</option>)}
            </select>
          </Field>
          <Field label={T.notes} hint="اختياري · تُحفظ الملاحظات مع هذه العينة">
            <textarea className="textarea" aria-label={T.notes} value={notes} rows={2}
              placeholder="أضف ملاحظة تساعد في مراجعة المتحدث…"
              onChange={(e) => onDraftChange({ role, notes: e.target.value })} disabled={!editable || busy} maxLength={2000} />
          </Field>
        </div>
        {editable && <div className="speaker-save-bar">
          <span className={dirty ? "speaker-unsaved" : "speaker-field-hint"} role="status">
            {dirty ? "تعديلات غير محفوظة" : "لا توجد تعديلات غير محفوظة"}
          </span>
          <div className="actions">
            {dirty && <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={() => onDraftChange(null)}>تراجع</button>}
            <button className="btn btn-primary" disabled={busy || !dirty} onClick={() => void save()} type="button" data-testid="speaker-save">
              <IconCheck />{busy ? "جارٍ الحفظ…" : "حفظ التعديلات"}
            </button>
          </div>
        </div>}
      </section>

      {(can("voice.enroll") || can("voice.identify")) && <section className="speaker-voice-tools">
        <div className="speaker-section-heading">
          <span className="speaker-tool-icon"><IconShield /></span>
          <div><h4>البصمة الصوتية <span className="speaker-optional">اختياري</span></h4>
            <p>{!speaker.has_voice_embedding ? "لا تتوفر عينة جاهزة للبصمة. راجع معالجة التسجيل أولاً." : !speaker.identity_id ? "حدّد هوية المتحدث أولاً لتتمكن من حفظ بصمته الصوتية." : "احفظ بصمة هذا الشخص للمساعدة في التعرّف عليه في التسجيلات القادمة."}</p></div>
        </div>
        <div className="speaker-voice-actions">
          {editable && <VoiceEnrollButton sessionId={sessionId} speaker={speaker} onEnrolled={onReloadRequested} />}
          {!speaker.has_voice_embedding && <Link className="speaker-text-link" data-testid="speaker-voice-sample-missing" to={`/investigations/${sessionId}?tab=recording`}>{T.voiceCheckRecording}<IconChevronLeft /></Link>}
        </div>
      </section>}

      <details className="speaker-source-details">
        <summary><IconInfo />تفاصيل المصدر والمعرّفات</summary>
        <dl><div><dt>رمز المتحدث</dt><dd><bdi>{speaker.speaker_label}</bdi></dd></div>
          <div><dt>معرّف العينة</dt><dd><bdi>{speaker.id}</bdi></dd></div>
          {speaker.recording_id && <div><dt>معرّف التسجيل</dt><dd><bdi>{speaker.recording_id}</bdi></dd></div>}</dl>
      </details>
    </div>
  );
}

export function SpeakersPanel({ sessionId, speakers, onChange, onReload }: {
  sessionId: string;
  speakers: Speaker[];
  onChange: (s: Speaker[]) => void;
  onReload?: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [rematching, setRematching] = useState(false);
  const [rematchResult, setRematchResult] = useState<VoiceRematchOutcome | null>(null);
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const [query, setQuery] = useState("");
  // Selection follows the observation even when identification moves it into a person group.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Keep unsaved edits when navigating between speakers or filtering the review queue.
  const [drafts, setDrafts] = useState<Record<string, SpeakerDraft>>({});
  useEffect(() => {
    setRematchResult(null); setSelectedId(null); setFilter("all"); setQuery(""); setDrafts({});
  }, [sessionId]);

  const rematch = async () => {
    setRematching(true);
    setRematchResult(null);
    try {
      const res = await http.post<VoiceRematchOutcome>(`/investigations/${sessionId}/voice-rematch`, {});
      setRematchResult(res);
      toast.success(res.suggested > 0 ? T.voiceRematchDone.replace("{n}", String(res.suggested)) : T.voiceRematchNone);
      onReload?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setRematching(false);
    }
  };

  const hasSuggestion = (speaker: Speaker) => can("voice.identify") && !speaker.identity_id && speaker.identification_status === "SUGGESTED" && !!speaker.suggested_name;
  const priority = (group: ReturnType<typeof groupSpeakerObservations>[number]) => group.observations.some(hasSuggestion) ? 0 : group.identified ? 2 : 1;
  const groups = groupSpeakerObservations(speakers).sort((a, b) => priority(a) - priority(b));
  const suggested = speakers.filter(hasSuggestion);
  const pending = speakers.filter(s => !s.identity_id);
  const identifiedCount = groups.filter(g => g.identified).length;
  const identifiedSamples = speakers.length - pending.length;
  const progress = speakers.length ? Math.round(identifiedSamples / speakers.length * 100) : 0;
  const search = query.trim().toLocaleLowerCase();
  const visibleGroups = groups.filter(g => (filter === "all" || (filter === "suggested" ? g.observations.some(hasSuggestion) : g.identified === (filter === "identified"))) &&
    (!search || [g.name, ...g.observations.flatMap(s => [can("voice.identify") ? s.suggested_name ?? "" : "", s.recording_name ?? "", s.speaker_label, t(`role_${s.speaker_role}`)])].some(text => text.toLocaleLowerCase().includes(search))));
  const activeGroup = visibleGroups.find(g => g.observations.some(s => s.id === selectedId)) ?? visibleGroups[0];
  const activeSpeaker = activeGroup?.observations.find(s => s.id === selectedId) ?? activeGroup?.observations[0];
  const groupTitle = (group: (typeof groups)[number]) => !group.identified && !group.observations[0].display_name
    ? `${group.name} ${speakers.findIndex(s => s.id === group.observations[0].id) + 1}` : group.name;
  const nextPending = pending.find((_, index) => index > pending.findIndex(p => p.id === activeSpeaker?.id)) ?? pending.find(s => s.id !== activeSpeaker?.id);
  const canRematch = can("voice.identify") && speakers.some(s => s.has_voice_embedding);

  return (
    <div className="speaker-workspace" data-testid="speaker-workspace">
      <header className="speaker-workspace-heading">
        <div><span className="speaker-eyebrow">مراجعة الجلسة / المتحدثون</span><h2>من يتحدث في التسجيل؟</h2>
          <p>راجع العينات الصوتية واربط كل صوت بالشخص الصحيح.</p></div>
        <div className="actions">
          {can("voice.identify") && <button className="btn" type="button" onClick={() => void rematch()} disabled={rematching || !canRematch} data-testid="voice-rematch"><IconRefresh />{rematching ? T.voiceRematchRunning : "البحث عن اقتراحات"}</button>}
          <Link className="btn" to={`/investigations/${sessionId}?tab=transcript`}><IconFile />عرض النص المفرغ<IconChevronLeft /></Link>
        </div>
      </header>

      {speakers.length === 0 ? <div className="speaker-empty card">
        <span className="speaker-empty-icon"><IconWave width={30} height={30} /></span>
        <h3>لا توجد عينات صوتية للمراجعة بعد</h3><p>أضف تسجيلاً وأكمل معالجته، ثم عُد إلى هنا لتحديد هوية المتحدثين.</p>
        <Link className="btn btn-primary" to={`/investigations/${sessionId}?tab=recording`}>الانتقال إلى التسجيل<IconChevronLeft /></Link>
      </div> : <>
        <div className="speaker-overview" aria-label="ملخص مراجعة المتحدثين">
          <div className="speaker-stat"><span className="speaker-stat-icon pending"><IconUsers /></span><div><strong>{pending.length}</strong><span>عينات بانتظار الهوية</span></div></div>
          <div className="speaker-stat"><span className="speaker-stat-icon identified"><IconCheck /></span><div><strong>{identifiedCount}</strong><span>أشخاص محددو الهوية</span></div></div>
          <div className="speaker-stat"><span className="speaker-stat-icon"><IconWave /></span><div><strong>{speakers.length}</strong><span>إجمالي العينات الصوتية</span></div></div>
          <div className="speaker-progress"><div><span>تقدّم تحديد الهوية</span><strong>{progress}%</strong></div>
            <progress value={identifiedSamples} max={speakers.length} aria-label="تقدّم تحديد الهوية" />
            <span>تم ربط {identifiedSamples} من {speakers.length} عينات</span></div>
        </div>

        {suggested.length > 0 && can("voice.identify") && <div className="speaker-suggestion-summary" data-testid="speaker-suggestion-summary">
          <IconWave /><div><strong>اقتراحات صوتية بانتظار المراجعة: {suggested.length}</strong><p>قد يكون الصوت لشخص من البصمات المحفوظة. راجع الاقتراح وأكّده ليظهر اسمه في المتحدثين والنص.</p></div>
          <button className="btn btn-primary btn-sm" type="button" onClick={() => { setQuery(""); setFilter("suggested"); setSelectedId(suggested[0].id); }} data-testid="review-voice-suggestions">مراجعة الاقتراحات</button>
        </div>}

        <div className={`speaker-guidance ${pending.length === 0 ? "is-complete" : ""}`}>
          {pending.length === 0 ? <IconCheck /> : <IconInfo />}
          <p><strong>{pending.length === 0 ? "تم تحديد هوية جميع العينات." : "ابدأ بالعينات التي تنتظر تحديد الهوية."}</strong>{" "}
            {pending.length === 0 ? "يمكنك مراجعة الصفات والملاحظات أو متابعة مراجعة النص." : "اختر عينة من القائمة، ثم حدّد الشخص واحفظ صفته وملاحظاتك."}</p>
        </div>

        <div className="speaker-review-layout">
          <aside className="speaker-queue" aria-label="قائمة المتحدثين">
            <div className="speaker-queue-heading"><h3>قائمة المتحدثين</h3><span>{groups.length}</span></div>
            <label className="speaker-search"><IconSearch /><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="ابحث عن اسم أو تسجيل…" aria-label="البحث في المتحدثين" /></label>
            <div className="speaker-filters" aria-label="تصفية المتحدثين">
              {([{ key: "all", label: "الكل", count: groups.length }, { key: "suggested", label: "اقتراحات", count: suggested.length }, { key: "pending", label: "بانتظار الهوية", count: pending.length }, { key: "identified", label: "محددون", count: identifiedCount }] as const).filter(f => f.key !== "suggested" || can("voice.identify")).map(f =>
                <button key={f.key} type="button" aria-pressed={filter === f.key} className={filter === f.key ? "active" : ""} onClick={() => setFilter(f.key)}>{f.label}<span>{f.count}</span></button>)}
            </div>
            <div className="speaker-queue-list">
              {visibleGroups.map(group => {
                const index = groups.indexOf(group);
                const hasDraft = group.observations.some(s => drafts[s.id] && (drafts[s.id].role !== s.speaker_role || drafts[s.id].notes !== (s.notes ?? "")));
                return <button type="button" key={group.key} className={`speaker-queue-item ${activeGroup?.key === group.key ? "is-active" : ""}`}
                  aria-current={activeGroup?.key === group.key ? "true" : undefined} aria-controls="speaker-review-detail"
                  onClick={() => setSelectedId(group.observations[0].id)} data-testid="speaker-person-group">
                  <span className="speaker-person-avatar" style={{ color: speakerColor(group.observations[0].speaker_label) }}>{group.identified ? <IconUsers /> : String(index + 1).padStart(2, "0")}</span>
                  <span className="speaker-queue-copy"><strong>{groupTitle(group)}</strong>
                    <span className={`speaker-queue-status ${group.identified ? "identified" : "pending"}`}>{group.identified ? "هوية محددة" : group.observations.some(hasSuggestion) ? "اقتراح بانتظار التأكيد" : "بانتظار تحديد الهوية"}</span>
                    {group.observations.some(hasSuggestion) && <span className="speaker-queue-suggestion">قد يكون: {group.observations.find(hasSuggestion)?.suggested_name}</span>}
                    <span className="speaker-queue-meta">{group.observations.length} عينات · {formatDuration(group.totalSeconds)}{hasDraft && <span className="speaker-draft-dot" title="تعديلات غير محفوظة" aria-label="تعديلات غير محفوظة" />}</span>
                    {(group.identified || group.observations[0].display_name) && groups.some(other => other.key !== group.key && other.name === group.name) && <span className="speaker-queue-meta">سجل مستقل {index + 1}</span>}
                  </span><IconChevronLeft />
                </button>;
              })}
              {visibleGroups.length === 0 && <div className="speaker-list-empty"><IconSearch /><p>لا توجد نتائج مطابقة</p><button className="btn btn-ghost btn-sm" type="button" onClick={() => { setQuery(""); setFilter("all"); }}>إظهار الجميع</button></div>}
            </div>
            <div className="speaker-queue-footnote"><IconInfo /><p>تُجمع العينات بعد ربطها بالشخص نفسه. تشابه الأسماء لا يعني تطابق الهوية.</p></div>
          </aside>

          <section className="speaker-review-detail" id="speaker-review-detail" aria-label="مراجعة المتحدث">
            {activeGroup && activeSpeaker ? <>
              <header className="speaker-detail-heading">
                <div><span className="speaker-eyebrow">مراجعة المتحدث</span><h3>{groupTitle(activeGroup)}</h3>
                  <span className="speaker-detail-meta">{activeGroup.segmentCount} مقاطع نصية <span>·</span> {formatDuration(activeGroup.totalSeconds)} من الحديث</span></div>
                <Badge kind={activeGroup.identified ? "green" : "amber"}>{activeGroup.identified ? "هوية محددة" : "بانتظار تحديد الهوية"}</Badge>
              </header>
              {activeGroup.observations.length > 1 && <div className="speaker-observation-tabs" aria-label="عينات الشخص">
                {activeGroup.observations.map((s, i) => <button type="button" key={s.id} className={`btn btn-sm ${activeSpeaker.id === s.id ? "btn-primary" : ""}`} aria-pressed={activeSpeaker.id === s.id} onClick={() => setSelectedId(s.id)}>العينة {i + 1}</button>)}
              </div>}
              <SpeakerForm key={activeSpeaker.id} sessionId={sessionId} speaker={activeSpeaker} draft={drafts[activeSpeaker.id]}
                observationNumber={activeGroup.observations.indexOf(activeSpeaker) + 1}
                onDraftChange={draft => setDrafts(previous => {
                  const updated = { ...previous };
                  if (draft) updated[activeSpeaker.id] = draft; else delete updated[activeSpeaker.id];
                  return updated;
                })}
                onSaved={updated => {
                  if (updated.identity_id && (filter === "suggested" || filter === "pending")) { setFilter("all"); setQuery(""); }
                  onChange(speakers.map(s => s.id === updated.id ? updated : s));
                }}
                onReloadRequested={() => { setSelectedId(activeSpeaker.id); onReload?.(); }} />
              {nextPending && <footer className="speaker-next"><span>تابع مراجعة العينات غير المحددة</span><button type="button" className="btn btn-ghost" onClick={() => { setQuery(""); setFilter("pending"); setSelectedId(nextPending.id); }}>العينة التالية<IconChevronLeft /></button></footer>}
            </> : <div className="speaker-empty"><IconUsers width={32} height={32} /><h3>اختر متحدثاً للمراجعة</h3><p>غيّر البحث أو التصفية لإظهار العينات الصوتية.</p></div>}
          </section>
        </div>

        {can("voice.identify") && <details className="speaker-matching-tools">
          <summary><IconRefresh /><span>أدوات مطابقة الأصوات</span><span className="speaker-optional">إعادة البحث عن تطابق</span></summary>
          <div className="speaker-matching-body"><div><h3>البحث في البصمات المحفوظة</h3><p>{T.voiceRematchHint}</p></div>
            {!canRematch && <p className="speaker-field-hint">لا تتوفر عينات جاهزة للمطابقة. راجع معالجة التسجيل.</p>}
          </div>
        </details>}
        {rematchResult && <div aria-live="polite"><VoiceRematchResult result={rematchResult} /></div>}
      </>}
    </div>
  );
}
