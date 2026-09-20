import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, fetchBlobUrl, http } from "@/api/client";
import type { BiometricCheck, BiometricPrintCheck, VoiceReview, VoiceReviewAction, VoiceSource } from "@/api/types";
import { Alert, Badge, Field, Loading, Modal } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatDuration } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { comparisonScore, printExplanation, printGroupLabel, reviewLabels } from "@/lib/voice-review";
import { IdentityConfirmationPanel } from "./IdentityConfirmationPanel";

const statusLabels = { COHERENT: T.voiceBioStatusCoherent, ISOLATED: T.voiceBioStatusIsolated,
  NEAR_DUPLICATE: T.voiceBioStatusNearDup, SINGLE_PRINT: T.voiceBioStatusSingle };
const overallLabels = { COHERENT: T.voiceBioOverallCoherent, REVIEW_REQUIRED: T.voiceBioOverallReview,
  SINGLE_PRINT: T.voiceBioOverallSingle, NO_PRINTS: T.voiceBioOverallNone };
const failure = (err: unknown) => err instanceof ApiError ? errorMessage(err.code) : T.err_generic;

function SourcePlayer({ row, title, onPlay }: { row: BiometricPrintCheck; title: string; onPlay: (audio: HTMLAudioElement) => void }) {
  const [source, setSource] = useState<VoiceSource | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [segment, setSegment] = useState(0);
  const audio = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setSource(null); setUrl(null); setError(null); setSegment(0);
    void (async () => {
      try {
        const next = await http.get<VoiceSource>(`/voice-enrollments/${row.enrollment_id}/source`);
        if (cancelled) return;
        const nextUrl = await fetchBlobUrl(`/recordings/${next.recording_id}/audio`);
        if (cancelled) { URL.revokeObjectURL(nextUrl); return; }
        objectUrl = nextUrl; setSource(next); setUrl(nextUrl);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError && [403, 404].includes(err.status)
          ? "المصدر غير متاح أو لا تملك صلاحية الوصول إليه." : failure(err));
      }
    })();
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [row.enrollment_id, attempt]);
  const window = source?.segments[segment];
  const start = () => {
    if (!audio.current || !window) return;
    audio.current.currentTime = window.start_seconds;
    void audio.current.play().catch(() => setError("تعذر التشغيل. حاول مجدداً."));
  };
  return <section className="card card-body" aria-label={title}>
    <strong>{title}</strong>
    <div className="muted small">{formatDateTime(row.created_at)}</div>
    {row.source_session_id && <Link to={`/investigations/${row.source_session_id}?tab=speakers`}>فتح جلسة المصدر</Link>}
    {error ? <><Alert kind="warning">{error}</Alert><button className="btn btn-sm" onClick={() => setAttempt(n => n + 1)}>إعادة المحاولة</button></>
      : !url || !source ? <Loading /> : <>
        <Field label="مقطع المتحدث">
          <select className="select" value={segment} onChange={e => {
            audio.current?.pause(); setSegment(Number(e.target.value));
            if (audio.current) audio.current.currentTime = source.segments[Number(e.target.value)].start_seconds;
          }}>
            {source.segments.map((s, i) => <option key={i} value={i}>{i + 1} — {formatDuration(s.start_seconds)} / {formatDuration(s.end_seconds)}</option>)}
          </select>
        </Field>
        <audio ref={audio} src={url} controls preload="metadata" style={{ width: "100%" }}
          onLoadedMetadata={() => { if (audio.current && window) audio.current.currentTime = window.start_seconds; }}
          onPlay={e => {
            if (window && (e.currentTarget.currentTime < window.start_seconds || e.currentTarget.currentTime >= window.end_seconds)) e.currentTarget.currentTime = window.start_seconds;
            onPlay(e.currentTarget);
          }}
          onTimeUpdate={e => { if (window && e.currentTarget.currentTime >= window.end_seconds) e.currentTarget.pause(); }}
          onError={() => setError("تعذر تحميل الصوت. حاول مجدداً.")} />
        <button className="btn btn-sm" type="button" onClick={start}>تشغيل المقطع المحدد</button>
      </>}
  </section>;
}

export function BiometricCheckModal({ initialResult, onClose }: { initialResult: BiometricCheck; onClose: () => void }) {
  const { can } = useAuth();
  const [result, setResult] = useState(initialResult);
  const [history, setHistory] = useState<VoiceReview[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [review, setReview] = useState<{ row: BiometricPrintCheck; action: VoiceReviewAction } | null>(null);
  const [reason, setReason] = useState("");
  const playing = useRef<HTMLAudioElement | null>(null);
  const rows = result.groups.flatMap(g => g.prints);
  const firstRow = rows.find(r => r.enrollment_id === first);
  const secondRow = rows.find(r => r.enrollment_id === second);
  const score = comparisonScore(result, first, second);
  const confirmedIds = new Set((result.identity_confirmations ?? []).filter(c => c.status === "ACTIVE").flatMap(c => c.enrollment_ids));
  const loadHistory = useCallback(async () => {
    setHistoryBusy(true); setHistoryError(null);
    try { setHistory(await http.get<VoiceReview[]>(`/voice-enrollments/people/${result.identity_id}/reviews`)); }
    catch (err) { setHistoryError(failure(err)); }
    finally { setHistoryBusy(false); }
  }, [result.identity_id]);
  useEffect(() => { void loadHistory(); }, [loadHistory]);
  const refresh = async () => {
    setBusy(true); setError(null); setReview(null); setSelected([]);
    try {
      setResult(await http.post<BiometricCheck>(`/voice-enrollments/people/${result.identity_id}/biometric-check`, {}));
      setStale(false);
    } catch (err) { setStale(true); setError(failure(err)); }
    finally { setBusy(false); }
  };
  const submit = async () => {
    if (!review || !reason.trim()) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      await http.post(`/voice-enrollments/${review.row.enrollment_id}/reviews`, {
        action: review.action, reason: reason.trim(), identity_id: result.identity_id,
        expected_updated_at: review.row.updated_at,
      });
      setReview(null); setReason(""); setNotice("تم حفظ الإجراء في سجل المراجعة.");
      setStale(true);
      await refresh(); await loadHistory();
    } catch (err) {
      if (err instanceof ApiError && err.code === "voice_review_stale") {
        setStale(true); setError("تغيرت البصمة منذ الفحص. أعد الفحص قبل اتخاذ إجراء جديد.");
      } else setError(failure(err));
    } finally { setBusy(false); }
  };
  const playOne = (audio: HTMLAudioElement) => { if (playing.current !== audio) playing.current?.pause(); playing.current = audio; };
  return <Modal size="lg" title={`${T.voiceBioCheckTitle} — ${result.person_name}`} onClose={() => { if (!busy) onClose(); }}>
    <div className="flex gap wrap" data-testid="bio-check-summary">
      <strong>نتيجة المقارنة الآلية: {overallLabels[result.overall_status]}</strong>
      <span>التأكيد اليدوي: {confirmedIds.size} من {rows.length} عينات</span>
      <span>{T.voiceBioActivePrints}: {result.total_active_prints}</span>
      <span>{T.voiceBioComponents}: <span data-testid="bio-components">{result.number_of_components}</span></span>
      <button className="btn btn-sm" disabled={busy} onClick={() => { void refresh(); void loadHistory(); }}>إعادة الفحص</button>
    </div>
    <p className="muted small">{T.voiceBioThresholds}: <bdi>{result.coherence_threshold.toFixed(2)} / {result.near_duplicate_threshold.toFixed(2)}</bdi>. درجة التشابه ليست احتمالاً للهوية.</p>
    {result.groups.length > 1 && <Alert kind="info">توجد عينات غير قابلة للمقارنة لاختلاف النموذج أو الإصدار أو مصدر الاستخراج. هذا لا يثبت اختلاف المتحدث.</Alert>}
    {result.groups.some(g => g.component_count > 1) && <Alert kind="warning">توجد مجموعات منفصلة بين عينات متوافقة تقنياً. استمع إلى المصادر قبل تعطيل أي بصمة.</Alert>}
    {notice && <Alert kind="success">{notice}</Alert>}
    {error && <Alert kind="danger">{error}</Alert>}
    {stale && <Alert kind="warning">النتيجة قديمة؛ أعد الفحص لتحديثها.</Alert>}
    {can("voice.enroll") && rows.length > 1 && <div className="card card-body mt-8">
      <strong>حدّد العينات لتأكيد وحدة الهوية — داخل المجموعة أو بين المجموعات</strong>
      <div className="flex gap wrap mt-8">
        <span aria-live="polite">المحدد: {selected.length}</span>
        <button className="btn btn-sm" disabled={busy || stale || rows.length > 100} onClick={() => setSelected(rows.map(r => r.enrollment_id))}>تحديد جميع العينات</button>
        <button className="btn btn-sm" disabled={busy || selected.length === 0} onClick={() => setSelected([])}>مسح التحديد</button>
        {can("transcripts.read") && <button className="btn btn-sm" disabled={busy || selected.length !== 2} onClick={() => { setFirst(selected[0]); setSecond(selected[1]); }}>مقارنة العينتين المحددتين</button>}
      </div>
    </div>}
    {result.groups.map((group, index) => <section className="mt-8" key={index}>
      <details className="muted small"><summary>بيانات المقارنة — {index + 1}</summary><bdi>{group.model} · {group.model_revision ?? "إصدار غير موثق"} · {group.provider ?? "مصدر غير موثق"}</bdi></details>
      {can("voice.enroll") && <div className="flex gap wrap mt-8">{[...new Set(group.prints.map(p => p.component_id))].map(component => <button className="btn btn-sm" key={component} disabled={busy || stale} onClick={() => setSelected(previous => [...new Set([...previous, ...group.prints.filter(p => p.component_id === component).map(p => p.enrollment_id)])])}>تحديد المجموعة {index + 1}.{component}</button>)}</div>}
      {group.prints.map(row => <div key={row.enrollment_id} className="card card-body mt-8" data-testid="bio-print-row">
        <div className="flex gap wrap">
          <strong>العينة {rows.indexOf(row) + 1}</strong><span>{formatDateTime(row.created_at)}</span>
          {can("voice.enroll") && <label className="flex gap"><input type="checkbox" aria-label={`تحديد العينة ${rows.indexOf(row) + 1}`} checked={selected.includes(row.enrollment_id)} disabled={busy || stale} onChange={e => setSelected(previous => e.target.checked ? [...previous, row.enrollment_id] : previous.filter(id => id !== row.enrollment_id))} />تحديد للتأكيد</label>}
          <Badge kind={row.status === "ISOLATED" ? "amber" : row.status === "SINGLE_PRINT" ? "gray" : "green"}>{statusLabels[row.status]}</Badge>
          {row.review_status === "FLAGGED" && <Badge kind="amber">بانتظار المراجعة</Badge>}
          {row.review_status === "RESOLVED" && <Badge kind="blue">تمت المراجعة</Badge>}
          <Badge kind="navy">{printGroupLabel(result, row.enrollment_id)}</Badge>
          {confirmedIds.has(row.enrollment_id) && <Badge kind="green">ضمن تأكيد يدوي</Badge>}
        </div>
        <p>{printExplanation(row, result)}</p>
        <p className="muted small">{row.peer_similarity_max != null && <>{T.voiceBioMaxSim}: <bdi>{row.peer_similarity_max.toFixed(2)}</bdi> · </>}{row.sample_seconds != null && <>مدة عينة الاستخراج: {formatDuration(row.sample_seconds)}</>}</p>
        <div className="flex gap wrap">
          {can("transcripts.read") && <button className="btn btn-sm" onClick={() => { setFirst(row.enrollment_id); setSecond(group.prints.find(r => r.enrollment_id !== row.enrollment_id)?.enrollment_id ?? ""); }}>استماع ومقارنة</button>}
          {can("voice.enroll") && (Object.keys(reviewLabels) as VoiceReviewAction[]).filter(a => a !== "RESOLVE" || row.review_status === "FLAGGED").map(action =>
            <button key={action} className="btn btn-sm" disabled={busy || stale} onClick={() => { setReview({ row, action }); setReason(""); setNotice(null); }}>{reviewLabels[action]}</button>)}
        </div>
      </div>)}
    </section>)}
    {review && <section className="card card-body mt-8" data-testid="voice-review-form">
      <strong>{reviewLabels[review.action]} — العينة {rows.findIndex(r => r.enrollment_id === review.row.enrollment_id) + 1}</strong>
      {review.action === "DEACTIVATE" && <Alert kind="warning">ستُستبعد هذه البصمة من المطابقات المقبلة، وستُلغى الاقتراحات المعلقة المبنية عليها. يمكنك إعادة تفعيلها من سجل البصمات.</Alert>}
      <Field label="سبب الإجراء / الملاحظة" required><textarea className="input" maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} disabled={busy} /></Field>
      <div className="flex gap"><button className="btn btn-primary" disabled={busy || stale || !reason.trim()} onClick={() => void submit()}>{review.action === "DEACTIVATE" ? "تأكيد التعطيل" : "حفظ المراجعة"}</button><button className="btn" disabled={busy} onClick={() => setReview(null)}>{T.cancel}</button></div>
    </section>}
    {firstRow && <section className="mt-8" aria-label="مقارنة عينتين">
      <p className="muted small">المقاطع من تفريغ التسجيل الأصلي؛ قد تختلف عن المقاطع المجمّعة التي استُخدمت لاستخراج البصمة.</p>
      <div className="form-grid">{["A", "B"].map((slot, i) => <Field key={slot} label={`العينة ${slot}`}><select className="select" value={i === 0 ? first : second} onChange={e => i === 0 ? setFirst(e.target.value) : setSecond(e.target.value)}><option value="">اختر عينة</option>{rows.filter(r => r.enrollment_id !== (i === 0 ? second : first)).map(r => <option key={r.enrollment_id} value={r.enrollment_id}>العينة {rows.indexOf(r) + 1} — {printGroupLabel(result, r.enrollment_id)} — {formatDateTime(r.created_at)}</option>)}</select></Field>)}</div>
      {secondRow && <p>{score === null ? "العينتان غير قابلتين للمقارنة تقنياً." : `درجة التشابه بين العينتين: ${score.toFixed(2)}`}</p>}
      <div className="form-grid"><SourcePlayer key={`a:${first}`} row={firstRow} title="العينة A" onPlay={playOne} />{secondRow && <SourcePlayer key={`b:${second}`} row={secondRow} title="العينة B" onPlay={playOne} />}</div>
      <button className="btn btn-sm" onClick={() => { setFirst(""); setSecond(""); }}>إغلاق المقارنة</button>
    </section>}
    <IdentityConfirmationPanel result={result} selected={selected} canManage={can("voice.enroll")} disabled={busy || stale}
      onBusy={setBusy} onStale={() => setStale(true)} onSaved={async () => { await refresh(); await loadHistory(); }} />
    <section className="mt-8" aria-label="سجل المراجعة">
      <h4>سجل المراجعة — أحدث ١٠٠ إجراء</h4>
      {historyBusy ? <Loading /> : historyError ? <><Alert kind="danger">{historyError}</Alert><button className="btn" onClick={() => void loadHistory()}>إعادة المحاولة</button></>
        : history.length === 0 ? <p className="muted">لا توجد إجراءات مراجعة مسجلة.</p>
        : history.map(entry => <div className="card card-body mt-8" key={entry.id}>
          <strong>{reviewLabels[entry.action]}</strong>
          <div className="muted small">{entry.reviewer_name ?? "مستخدم محذوف"} · {formatDateTime(entry.created_at)} · {rows.some(r => r.enrollment_id === entry.enrollment_id) ? `العينة ${rows.findIndex(r => r.enrollment_id === entry.enrollment_id) + 1}` : "بصمة غير فعالة أو محذوفة"}</div>
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{entry.reason}</p>
          <details className="muted small"><summary>معرّف البصمة</summary><bdi>{entry.enrollment_id}</bdi></details>
        </div>)}
    </section>
    <p className="muted small">{T.voiceBioAdvisory}</p>
  </Modal>;
}
